#!/usr/bin/env python3
import os
import sys
import json
import requests
import re

def debug_log(msg):
    if os.environ.get("DEBUG", "").lower() == "true":
        print(f"[DEBUG] {msg}")

def get_pr_diff():
    """
    Obtém o diff oficial da PR usando a API do GitHub.
    """
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not (token and repo and event_path):
        print("Variáveis de ambiente necessárias não definidas.")
        sys.exit(1)
    with open(event_path, "r") as f:
        event = json.load(f)
    pr_number = event.get("pull_request", {}).get("number")
    if not pr_number:
        print("Não foi possível identificar o número da PR.")
        sys.exit(1)
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3.diff"
    }
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        print("Erro ao obter o diff da PR:", response.status_code, response.text)
        sys.exit(1)
    return response.text

def get_repo_main_language():
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")  # formato: "owner/repo"
    
    if not token or not repo:
        print("⚠️ GITHUB_TOKEN ou GITHUB_REPOSITORY não definidos. Pulando detecção de linguagem.")
        return None

    url = f"https://api.github.com/repos/{repo}/languages"
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(url, headers=headers)
    
    if response.status_code != 200:
        print("⚠️ Falha ao obter linguagens do repositório:", response.status_code, response.text)
        return None

    languages = response.json()
    if not languages:
        return None
    
    main_language = max(languages, key=languages.get)
    return main_language

def filtrar_diff(diff_text, ignored_extensions):
    linhas = diff_text.splitlines()
    diff_filtrado = []
    ignorar = False
    current_file = None
    for linha in linhas:
        if linha.startswith("diff --git "):
            partes = linha.split()
            if len(partes) >= 4:
                current_file = partes[3][2:]
                if any(current_file.endswith(ext) for ext in ignored_extensions):
                    ignorar = True
                    debug_log(f"Ignorando arquivo {current_file} por extensão.")
                else:
                    ignorar = False
            else:
                ignorar = False
            if not ignorar:
                diff_filtrado.append(linha)
        else:
            if not ignorar:
                diff_filtrado.append(linha)
    return "\n".join(diff_filtrado)

def ler_diff(arquivo):
    try:
        with open(arquivo, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        print(f"Erro ao ler o diff: {e}")
        sys.exit(1)

def construir_prompt(diff, main_language=None):
    language_info = f"Este repositório utiliza predominantemente {main_language}.\n\n" if main_language else ""
    prompt = (
        "Segue abaixo o diff completo para análise, incluindo algumas linhas de contexto "
        "acima e abaixo das mudanças para fornecer mais clareza:\n\n"
        "```diff\n"
        f"{diff}\n"
        "```\n\n"
        "Você é um code reviewer experiente, com amplo conhecimento em diversas linguagens (por exemplo, Terraform, Go, React, Python e JavaScript). "
        "Sua tarefa é analisar o código acima, identificando e listando quaisquer problemas críticos, tais como erros de sintaxe, falhas de segurança, bugs críticos ou violações das boas práticas de programação, "
        "levando em conta as convenções de cada linguagem. Considere as seguintes orientações:\n\n"
        "1. Se uma atribuição de variável para uma string apresenta o valor entre aspas (simples ou duplas), essa sintaxe deve ser considerada correta.\n"
        "2. Linhas que contêm texto isolado (por exemplo, linhas de teste ou comentários informais) devem ser avaliadas com cautela e, se não fizerem parte do código funcional, não devem ser marcadas como erros críticos.\n"
        "3. Verifique se o código segue as convenções e boas práticas da linguagem em que foi escrito.\n\n"
        f"{language_info}"
        "Além disso, para cada problema crítico, identifique a localização exata no código, informando o caminho do arquivo e o número da linha onde o problema ocorreu, para que seja possível inserir um comentário inline na revisão do Pull Request.\n\n"
        "Responda no seguinte formato JSON:\n\n"
        "{\n"
        '  "problemas_criticos": [\n'
        '      {"arquivo": "caminho/do/arquivo", "linha": número_da_linha, "descricao": "descrição do problema"},\n'
        "      ...\n"
        "  ],\n"
        '  "sugestoes": ["sugestão 1", "sugestão 2", ...]\n'
        "}\n\n"
        "Caso não haja problemas críticos, a lista 'problemas_criticos' deverá ser vazia."
    )
    return prompt

def chamar_api_openai(prompt, token):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    url = "https://api.openai.com/v1/chat/completions"
    payload = {
        "model": "o3-mini",  # ou outro modelo disponível
        "messages": [
            {"role": "system", "content": "Você é um code reviewer."},
            {"role": "user", "content": prompt}
        ],
        "max_completion_tokens": 10000
    }
    
    response = requests.post(url, headers=headers, json=payload)
    
    if response.status_code != 200:
        print(f"Erro na chamada da API: {response.status_code} - {response.text}")
        sys.exit(1)
    
    return response.json()

def mapear_posicao(diff, target_file, target_line, line_offset=0):
    """
    Converte o número da linha do arquivo (target_line) para o valor de position
    do diff do arquivo target_file. A contagem é feita a partir da primeira linha
    imediatamente após o primeiro hunk header (a linha após "@@" é posição 1)
    e continua de forma contínua através do diff do arquivo.
    
    Um offset opcional (line_offset) pode ser somado para ajustes.
    """
    lines = diff.splitlines()
    file_block = []
    collecting = False
    # Isola o bloco do diff referente ao arquivo target_file
    for line in lines:
        if line.startswith("diff --git "):
            partes = line.split()
            if len(partes) >= 4:
                cur_file = partes[3][2:]
                if cur_file == target_file:
                    collecting = True
                    file_block = []  # reinicia o bloco para este arquivo
                else:
                    if collecting:
                        break  # finalizou o bloco do arquivo desejado
                    collecting = False
        elif collecting:
            file_block.append(line)
    if not file_block:
        return None

    cumulative_position = 0  # posição cumulativa no diff (ignorando cabeçalhos @@)
    simulated_line = None    # simula a numeração do novo arquivo para cada hunk
    found = False
    for line in file_block:
        if line.startswith("@@"):
            # Ao encontrar um cabeçalho de hunk, extraímos o número da primeira linha do novo arquivo
            m = re.search(r'\+(\d+)', line)
            if m:
                simulated_line = int(m.group(1))
            else:
                simulated_line = 0
            continue  # o cabeçalho não conta para a posição
        # Cada linha (não sendo cabeçalho) incrementa a posição cumulativa
        cumulative_position += 1
        # Se a linha é de contexto ou adição, ela faz parte do novo arquivo
        if line.startswith(" ") or line.startswith("+"):
            if simulated_line is None:
                simulated_line = 0  # garante que simulated_line seja um inteiro
            if simulated_line == target_line:
                found = True
                break
            simulated_line += 1
    if found:
        return cumulative_position + line_offset
    return None

def mapear_posicao_e_hunk(diff, target_file, target_line):
    try:
        offset = int(os.environ.get("LINE_OFFSET", "0"))
    except Exception:
        offset = 0
    pos = mapear_posicao(diff, target_file, target_line, offset)
    return pos, None

def post_review_to_pr(review_body, inline_comments, diff):
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("GITHUB_TOKEN não encontrado. Pulando a criação da review.")
        return

    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        print("GITHUB_REPOSITORY não definida. Não foi possível identificar o repositório.")
        return

    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        print("GITHUB_EVENT_PATH não definida. Não foi possível identificar o PR.")
        return

    with open(event_path, "r") as f:
        event = json.load(f)

    pr_number = None
    commit_id = None
    if "pull_request" in event:
        pr_number = event["pull_request"]["number"]
        # Extrai o SHA do commit HEAD do PR
        commit_id = event["pull_request"].get("head", {}).get("sha")
    elif "issue" in event and "pull_request" in event["issue"]:
        pr_number = event["issue"]["number"]

    if not pr_number:
        print("Não foi possível identificar o número do PR no payload do evento.")
        return

    if not commit_id:
        print("Não foi possível identificar o commit_id do PR.")
        return

    comentarios_inline = []
    comentarios_nao_inline = []
    for item in inline_comments:
        arquivo = item.get("arquivo")
        linha = item.get("linha")
        descricao = item.get("descricao")
        # Realiza o mapeamento da posição – ignoramos o diff_hunk
        pos, _ = mapear_posicao_e_hunk(diff, arquivo, linha)
        debug_log(f"Arquivo: {arquivo}, Linha: {linha}, Mapeado para posição: {pos}")
        if pos is not None:
            comentarios_inline.append({
                "path": arquivo,
                "position": pos,
                "body": descricao
            })
        else:
            # Se não conseguimos mapear para uma posição válida, adiciona no corpo da review
            comentarios_nao_inline.append(f"{arquivo}:{linha} -> {descricao}")

    if comentarios_nao_inline:
        review_body += "\n\nComentários adicionais:\n" + "\n".join(comentarios_nao_inline)

    payload = {
        "body": review_body,
        "event": "REQUEST_CHANGES",
        "commit_id": commit_id,
        "comments": comentarios_inline
    }
    debug_log(f"Payload da review: {json.dumps(payload, indent=2)}")

    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/reviews"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code in [200, 201]:
        print("💬 Review criada com sucesso no PR!")
    else:
        print(f"Falha ao criar review. Status code: {response.status_code}")
        print(response.text)

def processar_resposta(api_response):
    try:
        conteudo = api_response["choices"][0]["message"]["content"]
        resultado = json.loads(conteudo)
        return resultado
    except Exception as e:
        print("Erro ao processar a resposta da API. Exceção:", e)
        print("Resposta completa recebida:")
        print(json.dumps(api_response, indent=2, ensure_ascii=False))
        sys.exit(1)

def main():
    if len(sys.argv) < 2:
        print("🚨 Uso: python3 code_review.py <arquivo_diff>")
        sys.exit(1)
    
    diff = get_pr_diff()
    debug_log("Diff oficial obtido:")
    debug_log(diff)

    ignored_extensions = os.environ.get("IGNORE_EXTENSIONS", "")
    if ignored_extensions:
        ignored_list = [ext.strip() for ext in ignored_extensions.split(",") if ext.strip()]
        diff = filtrar_diff(diff, ignored_list)
    else:
        ignored_list = []

    if not diff.strip() or diff.strip() == "diff --git":
        print("ℹ️  O diff está vazio ou não contém alterações significativas. Pulando o code review.")
        sys.exit(0)
    
    main_language = get_repo_main_language()
    prompt = construir_prompt(diff, main_language)
    
    openai_token = os.environ.get("OPENAI_TOKEN")
    if not openai_token:
        print("🚨 Token da OpenAI não encontrado na variável de ambiente OPENAI_TOKEN.")
        sys.exit(1)
    
    print("🚀 Enviando prompt para a API da OpenAI...")
    api_response = chamar_api_openai(prompt, openai_token)
    resultado = processar_resposta(api_response)
    
    problemas = resultado.get("problemas_criticos", [])
    sugestoes = resultado.get("sugestoes", [])
    
    print("\n---- Resultados do Code Review ----")
    if problemas:
        print("❌ Problemas críticos encontrados:")
        for p in problemas:
            arquivo = p.get("arquivo", "arquivo não especificado")
            linha = p.get("linha", "linha não especificada")
            descricao = p.get("descricao", "sem descrição")
            print(f"  • {arquivo}:{linha} -> {descricao}")
    else:
        print("✅ Nenhum problema crítico encontrado!")
    
    if sugestoes:
        print("\n💡 Sugestões de melhoria:")
        for s in sugestoes:
            print(f"  • {s}")
    
    if problemas:
        review_body = "⚠️ **Code Review detectou problemas críticos!**\n\n" \
                      "Por favor, verifique os comentários inline para detalhes sobre as mudanças necessárias."
        post_review_to_pr(review_body, problemas, diff)
        print("\n⚠️ O Code Review detectou problemas críticos. Favor corrigir os itens listados e tentar novamente.")
        sys.exit(1)
    else:
        print("\n🎉 Code Review aprovado! Ótimo trabalho, continue assim! 👍")
        sys.exit(0)

if __name__ == '__main__':
    main()
