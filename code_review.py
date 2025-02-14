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
                # Se o arquivo casa com o padrão, marcamos para ignorar
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
    Mapeia a linha do arquivo (target_line) para a posição do diff onde
    o comentário inline deve ser inserido, considerando que a contagem
    reinicia a cada hunk (após a linha do cabeçalho @@).
    
    Retorna a posição (índice) relativa ao hunk, ou None se não encontrar.
    """
    lines = diff.splitlines()
    in_file = False
    file_block = []

    # Isola o bloco do diff referente ao arquivo target_file
    for line in lines:
        if line.startswith("diff --git "):
            partes = line.split()
            # O nome do arquivo de destino vem sem o "b/"
            current_file = partes[3][2:]
            if current_file == target_file:
                in_file = True
                file_block = []  # reinicia o bloco para esse arquivo
            else:
                if in_file:
                    # Se já estávamos coletando e mudou de arquivo, interrompe.
                    break
                in_file = False
        elif in_file:
            file_block.append(line)

    if not file_block:
        return None

    # Percorre o bloco do arquivo em busca dos hunks
    i = 0
    while i < len(file_block):
        line = file_block[i]
        if line.startswith("@@"):
            # Exemplo de cabeçalho de hunk:
            # @@ -50,10 +50,12 @@ func (s *CampaignTriggerService) Execute(...
            m = re.search(r'\+(\d+)(?:,(\d+))?', line)
            if m:
                new_start = int(m.group(1))
            else:
                new_start = 0

            # Reinicia a contagem para este hunk: a primeira linha depois do @@ é position 1.
            position_in_hunk = 0
            current_line = new_start  # corresponde à numeração do arquivo novo
            i += 1  # avança para as linhas do hunk
            while i < len(file_block) and not file_block[i].startswith("@@"):
                hunk_line = file_block[i]
                # Apenas linhas de contexto (" ") ou adição ("+") aparecem no arquivo novo.
                if hunk_line.startswith(" ") or hunk_line.startswith("+"):
                    position_in_hunk += 1
                    # Se a linha atual do arquivo novo for a desejada, retorna a posição no hunk.
                    if current_line == target_line:
                        return position_in_hunk + line_offset
                    current_line += 1
                # Linhas de deleção ("-") não são contadas no arquivo novo.
                i += 1
        else:
            i += 1

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
        print("🚨 Uso: python3 code_review.py <arquivo_diff> [ignore_regex]")
        sys.exit(1)
    
    diff_file = sys.argv[1]
    if os.path.exists(diff_file):
        diff = ler_diff(diff_file)
    else:
        diff = get_pr_diff()
    
    debug_log("Diff oficial obtido:")
    debug_log(diff)
    
    # Se o diff estiver vazio ou não tiver hunk(s), não há alterações significativas.
    if not diff.strip() or "@@" not in diff:
        print("ℹ️  O diff está vazio ou não contém alterações significativas. Pulando o code review.")
        sys.exit(0)
    
    # Se foi passado um padrão de regex para ignorar arquivos, aplica o filtro.
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
