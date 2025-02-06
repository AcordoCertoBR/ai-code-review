#!/usr/bin/env python3
import os
import sys
import json
import requests

def get_repo_main_language():
    """
    Obtém a linguagem predominante do repositório usando a API do GitHub.
    Retorna a linguagem como string ou None se não for possível determinar.
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

def post_comment_to_pr(comment):
    # Obtém o token do GitHub para autenticação
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("GITHUB_TOKEN não encontrado. Pulando o comentário no PR.")
        print("GITHUB_TOKEN:", os.environ.get("GITHUB_TOKEN"))
        return

    # Obtém o repositório a partir da variável de ambiente (no formato "owner/repo")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        print("GITHUB_REPOSITORY não definida. Não foi possível identificar o repositório.")
        return

    # Obtém o número do PR a partir do payload do evento
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        print("GITHUB_EVENT_PATH não definida. Não foi possível identificar o PR.")
        return

    with open(event_path, "r") as f:
        event = json.load(f)

    pr_number = None
    # Tenta identificar o número do PR (caso o evento seja pull_request)
    if "pull_request" in event:
        pr_number = event["pull_request"]["number"]
    elif "issue" in event and "pull_request" in event["issue"]:
        pr_number = event["issue"]["number"]

    if not pr_number:
        print("Não foi possível identificar o número do PR no payload do evento.")
        return

    # Define a URL para postar o comentário
    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    data = {"body": comment}
    response = requests.post(url, headers=headers, json=data)
    if response.status_code == 201:
        print("💬 Comentário postado com sucesso no PR!")
    else:
        print(f"Falha ao postar comentário. Status code: {response.status_code}")
        print(response.text)

def ler_diff(arquivo):
    try:
        with open(arquivo, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        print(f"Erro ao ler o diff: {e}")
        sys.exit(1)

def construir_prompt(diff, main_language=None):
    language_info = ""
    if main_language:
        language_info = f" Este repositório utiliza predominantemente {main_language}.\n\n"
    
    prompt = (
        "Segue abaixo o diff completo para análise:\n\n"
        "```diff\n"
        f"{diff}\n"
        "```\n\n"
        "Você é um code reviewer experiente, capaz de avaliar códigos escritos em diversas linguagens, "
        "incluindo " + language_info +
        "Sua tarefa é identificar e listar quaisquer problemas críticos no código, como erros de sintaxe, falhas "
        "de segurança, bugs críticos ou violações das boas práticas de programação, levando em conta as convenções "
        "de cada linguagem. Além disso, liste sugestões de melhoria que não sejam críticas.\n\n"
        "Responda no seguinte formato JSON:\n\n"
        "{\n"
        '  "problemas_criticos": ["descrição do problema 1", "descrição do problema 2", ...],\n'
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
    
    # print("Enviando payload para a API:")
    # print(json.dumps(payload, indent=2, ensure_ascii=False))
    
    response = requests.post(url, headers=headers, json=payload)
    
    # Log completo da resposta
    # print("Status Code da resposta:", response.status_code)
    # print("Cabeçalhos da resposta:", response.headers)
    # print("Conteúdo da resposta:", response.text)
    
    if response.status_code != 200:
        print(f"Erro na chamada da API: {response.status_code} - {response.text}")
        sys.exit(1)
    
    return response.json()

def processar_resposta(api_response):
    try:
        # Extraindo a resposta do modelo
        conteudo = api_response["choices"][0]["message"]["content"]
        # print("Conteúdo recebido do modelo:")
        # print(conteudo)
        # Tentando fazer o parse como JSON
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
    
    arquivo_diff = sys.argv[1]
    diff = ler_diff(arquivo_diff)
    
    # Verifica se o diff possui conteúdo significativo
    if not diff.strip() or diff.strip() == "diff --git":
        print("ℹ️  O diff está vazio ou não contém alterações significativas. Pulando o code review.")
        sys.exit(0)
    
    # Obtém a linguagem predominante do repositório
    main_language = get_repo_main_language()
    
    # Constrói o prompt, passando a linguagem predominante (se disponível)
    prompt = construir_prompt(diff, main_language)
    
    token = os.environ.get("OPENAI_TOKEN")
    if not token:
        print("🚨 Token da OpenAI não encontrado na variável de ambiente OPENAI_TOKEN.")
        sys.exit(1)
    
    print("🚀 Enviando prompt para a API da OpenAI...")
    api_response = chamar_api_openai(prompt, token)
    resultado = processar_resposta(api_response)
    
    # Exibindo os resultados:
    problemas = resultado.get("problemas_criticos", [])
    sugestoes = resultado.get("sugestoes", [])
    
    print("\n---- Resultados do Code Review ----")
    if problemas:
        print("❌ Problemas críticos encontrados:")
        for p in problemas:
            print(f"  • {p}")
    else:
        print("✅ Nenhum problema crítico encontrado!")
    
    if sugestoes:
        print("\n💡 Sugestões de melhoria:")
        for s in sugestoes:
            print(f"  • {s}")
    
    # Caso haja problemas críticos, posta um comentário no PR
    if problemas:
        comentario = "⚠️ **Code Review detectou problemas críticos!**\n\n"
        comentario += "Por favor, verifique os itens abaixo e realize as correções necessárias:\n"
        for p in problemas:
            comentario += f"• {p}\n"
        if sugestoes:
            comentario += "\n💡 *Além disso, algumas sugestões de melhoria foram apontadas:*\n"
            for s in sugestoes:
                comentario += f"• {s}\n"
        post_comment_to_pr(comentario)
        print("\n⚠️ O Code Review detectou problemas críticos. Favor corrigir os itens listados e tentar novamente.")
        sys.exit(1)
    else:
        print("\n🎉 Code Review aprovado! Ótimo trabalho, continue assim! 👍")
        sys.exit(0)

if __name__ == '__main__':
    main()
