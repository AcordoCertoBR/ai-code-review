# OpenAI Code Review Action

Esta GitHub Action realiza uma revisão automática de código utilizando a API da OpenAI. Quando acionada em um Pull Request, a Action analisa as mudanças no código e posta comentários no PR caso identifique problemas críticos ou sugestões de melhoria.

## 📌 Recursos

- Executa revisão de código automatizada utilizando a API da OpenAI.
- Detecta problemas críticos, falhas de segurança e más práticas de programação.
- Posta comentários diretamente no Pull Request com sugestões e correções necessárias.
- Suporte a múltiplas linguagens de programação, utilizando a API do GitHub para identificar a principal linguagem do repositório.

## 🚀 Como Usar

### 1️⃣ Configurar no repositório consumidor

Adicione o seguinte workflow no repositório que deseja utilizar a Action:

```yaml
name: Code Review with OpenAI

on:
  pull_request:
    types: [opened, synchronize, reopened]

jobs:
  code_review:
    runs-on: ubuntu-latest
    env:
      OPENAI_TOKEN: ${{ secrets.OPENAI_ENTERPRISE_TOKEN }}
      GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
    steps:
      - name: Executar Code Review com OpenAI
        uses: AcordoCertoBR/ai-code-review@v1.0.6
```

### 2️⃣ Configurar os Segredos do GitHub

Para que a Action funcione corretamente, é necessário adicionar os seguintes segredos no repositório:

- `OPENAI_ENTERPRISE_TOKEN`: Token de acesso à API da OpenAI.
- `GITHUB_TOKEN`: Token do GitHub (fornecido automaticamente pelo GitHub Actions, geralmente não precisa ser alterado).

## 🔍 Como Funciona

1. **Checkout do código**: A Action faz checkout do código do PR e obtém o `diff` entre a branch base e a branch da PR.
2. **Envio para análise**: O `diff` é enviado para a API da OpenAI com um prompt instruindo a IA a revisar o código.
3. **Processamento da resposta**: A IA retorna um JSON com problemas críticos e sugestões de melhoria.
4. **Publicação no PR**: Se houver problemas críticos, um comentário é postado automaticamente no PR com detalhes das falhas e sugestões.
5. **Aprovação ou Reprovação**: Se não houver problemas críticos, o Code Review é aprovado.

## 🎯 Exemplo de Comentário Postado

> ⚠️ **Code Review detectou problemas críticos!**
> - Erro de sintaxe na linha 25 do arquivo `app.py`.
> - Uso inseguro de entrada de usuário na função `process_input()`.
>
> 💡 *Sugestões de melhoria:*
> - Considere refatorar a função `calculate_total()` para reduzir a complexidade.
> - Utilize `f-strings` ao invés de `.format()` para melhorar a legibilidade do código Python.

## 🛠 Desenvolvimento

Caso queira contribuir ou modificar a Action, siga os passos abaixo:

1. Clone o repositório:
   ```sh
   git clone https://github.com/AcordoCertoBR/ai-code-review.git
   ```
2. Instale as dependências (se necessário).
3. Modifique os arquivos `code_review.py` ou a Action YAML conforme necessário.
4. Teste localmente e publique uma nova versão se necessário.

## 📜 Licença

Este projeto está licenciado sob a licença MIT. Veja o arquivo [LICENSE](LICENSE) para mais detalhes.

---

Caso tenha dúvidas ou sugestões, sinta-se à vontade para abrir uma Issue ou contribuir com um Pull Request! 🚀

