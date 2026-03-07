# Sistema de Correção Automática de Provas com IA — 1 Questão

Correção assíncrona de submissões do Moodle VPL usando a API Groq (LLMs).  
Para cada aluno, gera um `rubrica.txt` com a análise da IA e o compara com a nota atribuída pelo Moodle.

> ⚠️ **A nota final sempre é atribuída pelo professor com avaliação manual.**  
> A correção da IA é apenas um apoio ao processo de aprendizagem e pode conter imprecisões.

---

## Arquivos do Projeto

```
.
├── runProva1q.sh           ← script principal (entrypoint)
├── grader1q.py             ← orquestrador assíncrono
├── llm_interface_prova.py  ← cliente LLM (aiohttp + retry)
├── enviar_email.py         ← envio de feedbacks por e-mail (opcional)
├── config.yaml             ← suas credenciais e configurações (NÃO versionar)
├── config.yaml.example     ← template de configuração
├── prompt1q.txt            ← instruções + enunciado da questão para a IA
└── Simulado0/              ← pasta com submissões dos alunos (gerada pelo Moodle)
    ├── Nome Aluno - login/
    │   ├── 2026-03-04-10-14-39/       ← última submissão (pasta timestamp)
    │   │   └── solucao.py             ← código do aluno
    │   └── 2026-03-04-10-14-39.ceg/
    │       └── execution.txt          ← correção automática do Moodle
    └── ...
```

---

## Pré-requisitos

- Python 3.8+
- Conta gratuita em [console.groq.com](https://console.groq.com) para obter a API Key
- Dependências Python:

```bash
pip install aiohttp pyyaml
```

---

## Configuração Inicial

### 1. Copiar o template de configuração

```bash
cp config.yaml.example config.yaml
```

Edite o `config.yaml` e preencha:

```yaml
# Credenciais de e-mail (para enviar feedbacks, se desejar)
email:
  smtp_server: smtp.ufabc.edu.br
  smtp_port: 587
  from_address: seu_email@ufabc.edu.br
  password: "sua_senha"

# Chave da API Groq
groq:
  api_key: "gsk_..."       # obtenha em console.groq.com/keys

# Configuração da prova
grading:
  weights:
    q1: 100                # pontuação máxima da questão
  prompt_file: "prompt1q.txt"

# Pasta das submissões
paths:
  student_base_dir: "Simulado0"
```

> ⚠️ **Nunca versione o `config.yaml`**. Adicione-o ao `.gitignore`:
> ```
> config.yaml
> ```

### 2. Criar o prompt da questão

Crie o arquivo `prompt1q.txt` com as instruções para a IA e o enunciado da questão. Exemplo:

```
Você é um professor corretor. Avalie o código Python abaixo segundo os critérios:

Critério 1 - Entrada e Tipagem (máx: 10 pts): ...
Critério 2 - Lógica (máx: 60 pts): ...
Critério 3 - Saída formatada (máx: 30 pts): ...

Ao final, escreva obrigatoriamente uma linha no formato:
Nota: X + Y + Z = TOTAL/100
```

A linha de nota no formato `= TOTAL/100` garante a extração automática da nota pelo sistema.

---

## Baixar as Submissões do Moodle VPL

1. Acesse a atividade **VPL** no Moodle
2. Clique em **Lista de envios**
3. Na tabela de alunos, localize a **seta para baixo** (⬇) no cabeçalho da tabela — fica discreto, no canto direito do cabeçalho
4. Clique em **Baixar envios** ou **Baixar todos os envios**  
   — o sistema já considera automaticamente a **última submissão** de cada aluno
5. Descompacte o arquivo `.zip` baixado
6. Mova a pasta descompactada para dentro do projeto:

```bash
mv ~/Downloads/Simulado0 ./Simulado0
```

A estrutura resultante deve ser:

```
Simulado0/
├── Sobrenome1 Nome1 - aluno.1/
│   ├── 2026-03-02-09-50-00/
│   │   └── solucao.py
│   └── 2026-03-02-09-50-00.ceg/
│       └── execution.txt
├── Sobrenome2 Nome2 - aluno.2/
│   └── ...
└── ...
```

> **RENOMEAR PASTAS:** Corrigir os nomes das pastas dos alunos para `Nome Sobrenome - login`, usando o script:

```bash
renomear_pastas.sh Simulado0
```
---

## Execução da Correção

```bash
chmod +x runProva1q.sh
./runProva1q.sh Simulado0
```

Opções disponíveis:

```bash
./runProva1q.sh <pasta_alunos> [config.yaml] [--max-concurrent N]

# Exemplos:
./runProva1q.sh Simulado0
./runProva1q.sh Simulado0 config.yaml
./runProva1q.sh Simulado0 config.yaml --max-concurrent 5
```

O parâmetro `--max-concurrent` controla quantas chamadas à API Groq ocorrem simultaneamente. O padrão é `3`, adequado para o plano gratuito (limite de 30 req/min).

### O que acontece durante a execução

1. O script valida o ambiente (Python, dependências, arquivos)
2. Para cada aluno, localiza a **última submissão** (pasta com o timestamp mais recente)
3. Envia o código + prompt para a API Groq de forma **assíncrona** — todos os alunos são processados em paralelo, respeitando o limite de concorrência
4. Se a LLM não responder, tenta automaticamente outros modelos da lista com backoff exponencial
5. Só grava o `rubrica.txt` se a LLM retornar uma resposta válida
6. Ao final, consolida todos os resultados em `Simulado0_ALL.txt`

### Saída gerada

Após a execução, cada aluno terá:

```
Simulado0/Nome Aluno - login/TIMESTAMP/rubrica.txt
```

E o consolidado geral:

```
Simulado0_ALL.txt
```

Para visualizar todos os resultados de uma vez:

```bash
cat Simulado0_ALL.txt | less
```

---

## Estrutura do rubrica.txt

Cada `rubrica.txt` contém:

| Seção | Conteúdo |
|---|---|
| Cabeçalho | Nome do aluno e data de geração |
| Correção Moodle | Nota extraída do `execution.txt` (se disponível) |
| Código submetido | Código-fonte do aluno |
| Avaliação da IA | Análise detalhada por critério |
| Resumo | Comparativo Moodle × IA com diferença em pontos |
| Log bruto Moodle | Saída completa do `execution.txt` |

---

## Envio de Feedbacks por E-mail (Opcional)

O script `enviar_email.py` envia o `rubrica.txt` como anexo para cada aluno.

Antes de usar, configure as credenciais SMTP no `config.yaml` e ajuste no script:

- `PASTA_BASE` — pasta com as submissões (ex: `"Simulado0"`)
- `email_destino` — durante testes, redirecione para seu próprio e-mail  
  (`email_destino = 'seu@@aluno.ufabc.edu.br'`)
- `assunto` — personalize conforme a prova
- O texto do e-mail em `config.yaml` — ajuste em `templates`.
- Para produção, comentar a linha 138 de `enviar_email.py`:
  > `email_to = "fzampirolli@gmail.com" # TESTE`


Para executar:

```bash
python3 enviar_email.py
```

> ⚠️ **Atenção:** O e-mail deixa explícito que a correção é gerada por IA e pode conter imprecisões. **A nota oficial sempre é a atribuída pelo professor no Moodle.**

---

## Modelos LLM Disponíveis

Configurados em `config.yaml` na seção `groq.models`. O sistema tenta cada modelo em ordem e passa para o próximo em caso de falha:

| Modelo | Observação |
|---|---|
| `llama-3.3-70b-versatile` | Melhor qualidade geral |
| `openai/gpt-oss-120b` | Alta capacidade |
| `llama-3.1-8b-instant` | Mais rápido, menor qualidade |
| `openai/gpt-oss-20b` | Rápido |

O plano gratuito do Groq permite **30 requisições por minuto**. Para turmas grandes, ajuste `--max-concurrent` para `2` ou `3`.

---

## Solução de Problemas

**`❌ Execute com bash: bash runProva1q.sh`**  
O script requer bash. Execute explicitamente: `bash runProva1q.sh Simulado0`

**Nota Moodle aparece como `0.00` ou `N/A`**  
Verifique se existe a pasta `TIMESTAMP.ceg/execution.txt` para o aluno.  
O sistema extrai a nota do padrão `Grade :=>>100` no arquivo.

**Nota da IA aparece como `?`**  
O prompt não gerou uma linha de nota no formato esperado (`= TOTAL/100`).  
Revise o `prompt1q.txt` para instruir explicitamente a IA a escrever a nota nesse formato.

**Erro HTTP 400 (`max_tokens`)**  
O `max_response_chars` no `config.yaml` está acima do limite da Groq.  
O sistema já limita automaticamente a 8192 tokens internamente.

**Nenhum arquivo de código encontrado**  
Extensões suportadas: `.py`, `.java`, `.c`, `.cpp`, `.js`, `.ts`.  
Verifique se os arquivos estão diretamente dentro da pasta de timestamp, não em subpastas.

---

## Segurança

- `config.yaml` contém sua API key e senha de e-mail — **nunca suba para o Git**
- Adicione ao `.gitignore`:

```
config.yaml
*.env
logs/
*_ALL.txt
```