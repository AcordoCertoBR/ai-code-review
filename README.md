# OpenAI Code Review Action

Esta GitHub Action executa um code review automatizado utilizando a API da OpenAI e cria comentários inline no Pull Request caso sejam identificados problemas críticos.

## 📌 Funcionalidades

- Obtém automaticamente o `diff` do Pull Request.
- Filtra arquivos/diretórios a serem ignorados utilizando expressões regulares.
- Envia o `diff` para a API da OpenAI para análise.
- Cria comentários inline no Pull Request apontando problemas críticos detectados.
- Sugere melhorias gerais no código.

## 🚀 Como Usar

Adicione o seguinte workflow ao repositório para executar a Action sempre que um Pull Request for aberto, atualizado ou reaberto:

```yaml
ame: AI Code Review

on:
  pull_request:
    types: [opened, synchronize, reopened]

jobs:
  run:
    runs-on: ubuntu-latest
    env:
      OPENAI_TOKEN: ${{ secrets.OPENAI_ENTERPRISE_TOKEN }}
      GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
      DEBUG: true
    steps:
      - name: Executar Code Review com OpenAI
        uses: AcordoCertoBR/ai-code-review@v1.0.38
        with:
          ignore_regex: "^(?:\.github/|.*vendor/.*|.*\.(?:json|xml)$|go\.(?:mod|sum)$)"
```

## 📥 Entradas (Inputs)

| Nome           | Descrição                                                                    | Obrigatório | Padrão |
| -------------- | ---------------------------------------------------------------------------- | ----------- | ------ |
| `ignore_regex` | Regex para ignorar arquivos/diretórios no diff do PR. Exemplo: `.*vendor/.*` | Não         | `""`   |

## 📤 Saídas (Outputs)

Atualmente, esta Action não possui saídas explícitas.

## 🛠️ Como Funciona

1. **Checkout do código**: Baixa o código do repositório para análise.
2. **Obtém o **``** do PR**: Recupera as mudanças entre a base e o branch do PR.
3. **Filtra arquivos ignorados**: Remove do `diff` arquivos/diretórios que casam com o regex de exclusão.
4. **Consulta a API da OpenAI**: Envia o `diff` filtrado para análise.
5. **Gera comentários inline no PR**: Caso problemas críticos sejam detectados, adiciona comentários diretamente no código do Pull Request.

## ⚙️ Configuração de Tokens

Esta ação requer dois segredos configurados no repositório:

- ``: Token de acesso à API da OpenAI.
- ``: Token padrão do GitHub para interações no PR.

Para configurar os segredos:

1. Vá até o repositório no GitHub.
2. Acesse **Settings** → **Secrets and variables** → **Actions**.
3. Clique em **New repository secret** e adicione os tokens necessários.

## 📜 Licença

Este projeto está sob a licença MIT. Veja o arquivo `LICENSE` para mais detalhes.

## 💡 Contribuições

Contribuições são bem-vindas! Sinta-se à vontade para abrir um Pull Request ou criar uma Issue caso encontre problemas ou tenha sugestões.

---

💬 Caso tenha dúvidas ou precise de ajuda, entre em contato abrindo uma Issue no repositório!