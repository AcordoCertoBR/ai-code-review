#!/usr/bin/env python3
import os
import sys
import json
import requests
import re

def get_repo_main_language():
    """
    Obtém a linguagem predominante do repositório usando a API do GitHub.
    """
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
    
    # Seleciona a linguagem com o maior número de bytes
    main_language = max(languages, key=languages.get)
    return main_language

def filtrar_diff(diff_text, ignored_extensions):
    """
    Filtra o diff removendo blocos de arquivos que possuem extensões ignoradas.
    """
    linhas = diff_text.splitlines()
    diff_filtrado = []
    ignorar = False
    current_file = None
    for linha in linhas:
        if linha.startswith("diff --git "):
            # Exemplo: diff --git a/path/to/file b/path/to/file
            partes = linha.split()
            if len(partes) >= 4:
                # Obtém o caminho do arquivo novo (b/...)
                current_file = partes[3][2:]
                # Verifica se a extensão do arquivo está na lista de ignorados
                if any(current_file.endswith(ext) for ext in ignored_extensions):
                    ignorar = True
                else:
                    ignorar = False
            else:
                ignorar = False
            if not ignorar:
                diff_filtrado.append(linha)
        else:
            if not ignorar:
                diff_filtrado.append(linha)
    diff_resultante = "\n".join(diff_filtrado)
    return diff_resultante

def ler_diff(arquivo):
    try:
        with open(arquivo, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        print(f"Erro ao ler o diff: {e}")
        sys.exit(1)

def construir_prompt(diff, main_language=None):
    """
    Constrói o prompt a ser enviado para a API da OpenAI.
    Agora, solicita que o retorno contenha para cada problema crítico:
      - "arquivo": caminho do arquivo;
      - "linha": número da linha (no novo arquivo);
      - "descricao": descrição do problema.
    """
    language_info = ""
    if main_language:
        language_info = f"Este repositório utiliza predominantemente {main_language}.\n\n"
    
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
        "max_tokens": 10000
    }
    
    response = requests.post(url, headers=headers, json=payload)
    
    if response.status_code != 200:
        print(f"Erro na chamada da API: {response.status_code} - {response.text}")
        sys.exit(1)
    
    return response.json()

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

def mapear_linha_para_posicao(diff, target_file, target_line):
    """
    Mapeia o número da linha do arquivo (novo) para a posição correspondente no diff.
    Retorna a posição (inteiro) ou None se não encontrar.
    
    Essa função percorre o diff procurando a seção referente a 'target_file' e,
    dentro dela, usa os cabeçalhos dos hunks (@@) para identificar a numeração do novo arquivo.
    """
    linhas = diff.splitlines()
    pos_diff = 0
    current_file = None
    new_line_num = None
    for linha in linhas:
        pos_diff += 1
        # Detecta início de um novo arquivo no diff
        if linha.startswith("diff --git "):
            partes = linha.split()
            if len(partes) >= 4:
                # Extrai o caminho do novo arquivo (b/...)
                current_file = partes[3][2:]
            new_line_num = None
        elif linha.startswith("@@"):
            # Exemplo de hunk: @@ -start_old,count_old +start_new,count_new @@
            m = re.search(r'\+(\d+)(?:,(\d+))?', linha)
            if m:
                new_line_num = int(m.group(1))
            else:
                new_line_num = None
        else:
            if new_line_num is not None and current_file == target_file:
                # Considera linhas adicionadas ou de contexto (não incrementa em remoções)
                if linha.startswith('+') or linha.startswith(' '):
                    if new_line_num == target_line:
                        return pos_diff
                    new_line_num += 1
    return None

def post_review_to_pr(review_body, inline_comments, diff):
    """
    Cria uma revisão (review) no PR usando a API do GitHub com os comentários inline.
    Cada comentário possui:
      - path: o arquivo (relativo)
      - position: a posição no diff (calculada via mapear_linha_para_posicao)
      - body: a mensagem do comentário
    Se algum comentário não conseguir ser mapeado para uma posição, ele é adicionado ao corpo geral da review.
    """
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
    if "pull_request" in event:
        pr_number = event["pull_request"]["number"]
    elif "issue" in event and "pull_request" in event["issue"]:
        pr_number = event["issue"]["number"]

    if not pr_number:
        print("Não foi possível identificar o número do PR no payload do evento.")
        return

    # Monta os comentários inline com posição no diff
    comentarios_inline = []
    comentarios_nao_inline = []
    for item in inline_comments:
        arquivo = item.get("arquivo")
        linha = item.get("linha")
        descricao = item.get("descricao")
        pos = mapear_linha_para_posicao(diff, arquivo, linha)
        if pos is not None:
            comentarios_inline.append({
                "path": arquivo,
                "position": pos,
                "body": descricao
            })
        else:
            # Se não encontrou a posição, adiciona ao comentário geral
            comentarios_nao_inline.append(f"{arquivo}:{linha} -> {descricao}")

    # Se houver comentários não inline, adiciona-os ao corpo da review
    if comentarios_nao_inline:
        review_body += "\n\nComentários adicionais:\n" + "\n".join(comentarios_nao_inline)

    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/reviews"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "body": review_body,
        "event": "REQUEST_CHANGES",
        "comments": comentarios_inline
    }
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code in [200, 201]:
        print("💬 Review criada com sucesso no PR!")
    else:
        print(f"Falha ao criar review. Status code: {response.status_code}")
        print(response.text)

def main():
    if len(sys.argv) < 2:
        print("🚨 Uso: python3 code_review.py <arquivo_diff>")
        sys.exit(1)
    
    arquivo_diff = sys.argv[1]
    diff = ler_diff(arquivo_diff)

    # Lê as extensões ignoradas a partir da variável de ambiente IGNORE_EXTENSIONS (input da action)
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
    
    # Se houver problemas críticos, cria uma review no PR com comentários inline
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
