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

def filtrar_diff(diff_text, ignore_pattern):
    """
    Filtra o diff removendo os blocos de arquivos cujo nome casa com o padrão de regex fornecido.
    Se ignore_pattern for uma string vazia, retorna o diff sem alterações.
    """
    if not ignore_pattern:
        return diff_text

    linhas = diff_text.splitlines()
    diff_filtrado = []
    ignorar = False
    current_file = None

    for linha in linhas:
        if linha.startswith("diff --git "):
            partes = linha.split()
            if len(partes) >= 4:
                # O nome do arquivo vem após "b/"
                current_file = partes[3][2:]
                if re.search(ignore_pattern, current_file):
                    ignorar = True
                    debug_log(f"Ignorando arquivo {current_file} por regex '{ignore_pattern}'.")
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
        "Sua tarefa é analisar o código acima, identificando e listando quaisquer problemas críticos, tais como erros de sintaxe, falhas de segurança, bugs críticos ou violações das boas práticas de programação. "
        "Além disso, para cada problema crítico, identifique a localização exata no diff onde o problema ocorreu. "
        "A contagem das posições deve iniciar imediatamente após o cabeçalho do hunk (a linha que começa com '@@'). A primeira linha logo após esse cabeçalho é considerada posição 1. "
        "Use essa contagem para indicar com precisão a localização dos problemas, independentemente do diff analisado, sem utilizar exemplos específicos do diff atual.\n\n"
        "Responda no seguinte formato JSON:\n\n"
        "{\n"
        '  "problemas_criticos": [\n'
        '      {"arquivo": "caminho/do/arquivo", "posicao": número_da_posicao, "descricao": "descrição do problema"},\n'
        "      ...\n"
        "  ],\n"
        '  "sugestoes": ["sugestão 1", "sugestão 2", ...]\n'
        "}\n\n"
        "Caso não haja problemas críticos, a lista 'problemas_criticos' deverá ser vazia."
    )
    debug_log("Prompt enviado para a API do OpenAI:")
    debug_log(prompt)
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
    debug_log("Resposta da API do OpenAI:")
    debug_log(response.text)
    
    if response.status_code != 200:
        print(f"Erro na chamada da API: {response.status_code} - {response.text}")
        sys.exit(1)
    
    return response.json()

def mapear_posicao(diff, target_file, target_line, line_offset=0):
    """
    Mapeia a linha do arquivo (target_line) para a posição do diff onde
    o comentário inline deve ser inserido. A contagem é feita acumulando os hunks
    do diff do arquivo target_file. Dentro de cada hunk, a contagem reinicia 
    (a linha imediatamente abaixo do cabeçalho "@@" é considerada posição 1) e é acumulada 
    ao longo dos hunks.
    
    Contamos todas as linhas que não começam com "-" (remoções).
    Retorna o valor de position (um inteiro) ou None se não encontrar.
    """
    lines = diff.splitlines()
    in_file = False
    file_block = []

    # Isola o bloco do diff referente ao arquivo target_file
    for line in lines:
        if line.startswith("diff --git "):
            partes = line.split()
            current_file = partes[3][2:]
            if current_file == target_file:
                in_file = True
                file_block = []
            else:
                if in_file:
                    break
                in_file = False
        elif in_file:
            file_block.append(line)

    if not file_block:
        return None

    total_position = 0  # posição acumulada do diff para o arquivo
    i = 0
    while i < len(file_block):
        line = file_block[i]
        if line.startswith("@@"):
            # Cabeçalho do hunk: extrai o número da primeira linha do novo arquivo.
            m = re.search(r'\+(\d+)(?:,(\d+))?', line)
            if m:
                new_start = int(m.group(1))
            else:
                new_start = 0

            hunk_position = 0  # contagem relativa no hunk: a primeira linha após o header é 1
            simulated_line = new_start
            i += 1  # pula o cabeçalho
            while i < len(file_block) and not file_block[i].startswith("@@") and not file_block[i].startswith("diff --git "):
                hunk_line = file_block[i]
                hunk_position += 1
                # Contamos a linha se ela não for uma remoção.
                if not hunk_line.startswith("-"):
                    if simulated_line == target_line:
                        return total_position + hunk_position + line_offset
                    simulated_line += 1
                i += 1
            total_position += hunk_position
        else:
            i += 1

    return None

def mapear_posicao_e_hunk(diff, target_file, target_line):
    try:
        offset = int(os.environ.get("LINE_OFFSET", "0"))
    except Exception:
        offset = 0
    # Aqui assumimos que target_line é o número original e queremos a posição no diff,
    # mas como o modelo agora deve retornar a posição no diff, usaremos esse valor diretamente.
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
        # Aqui esperamos que o modelo retorne a chave "posicao" em vez de "linha"
        posicao = item.get("posicao")
        descricao = item.get("descricao")
        if posicao is not None:
            comentarios_inline.append({
                "path": arquivo,
                "position": posicao,
                "body": descricao
            })
        else:
            comentarios_nao_inline.append(f"{arquivo}: posição desconhecida -> {descricao}")

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

def approve_review():
    """
    Envia uma nova review com evento APPROVE para o PR, encerrando revisões anteriores.
    """
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not (token and repo and event_path):
        print("Variáveis de ambiente necessárias não definidas para aprovar a review.")
        return

    with open(event_path, "r") as f:
        event = json.load(f)

    pr_number = None
    commit_id = None
    if "pull_request" in event:
        pr_number = event["pull_request"]["number"]
        commit_id = event["pull_request"].get("head", {}).get("sha")
    elif "issue" in event and "pull_request" in event["issue"]:
        pr_number = event["issue"]["number"]

    if not pr_number or not commit_id:
        print("Não foi possível identificar o número do PR ou o commit_id.")
        return

    payload = {
        "body": "Todos os problemas críticos foram resolvidos. Aprovação automática da revisão.",
        "event": "APPROVE",
        "commit_id": commit_id
    }

    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/reviews"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code in [200, 201]:
        print("💬 Review aprovada com sucesso!")
    else:
        print(f"Falha ao aprovar review. Status code: {response.status_code}")
        print(response.text)

def main():
    if len(sys.argv) < 2:
        print("🚨 Uso: python3 code_review.py <arquivo_diff> [ignore_regex]")
        sys.exit(1)
    
    diff_file = sys.argv[1]
    if os.path.exists(diff_file):
        diff = ler_diff(diff_file)
    else:
        diff = get_pr_diff()
    
    debug_log("Diff oficial obtido:")
    debug_log(diff)
    
    if not diff.strip() or "@@" not in diff:
        print("ℹ️  O diff está vazio ou não contém alterações significativas. Pulando o code review.")
        sys.exit(0)
    
    ignore_pattern = sys.argv[2] if len(sys.argv) > 2 else ""
    if ignore_pattern:
        diff = filtrar_diff(diff, ignore_pattern)
    
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
            posicao = p.get("posicao", "posição não especificada")
            descricao = p.get("descricao", "sem descrição")
            print(f"  • {arquivo}:posição {posicao} -> {descricao}")
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
        approve_review()
        sys.exit(0)

if __name__ == '__main__':
    main()
