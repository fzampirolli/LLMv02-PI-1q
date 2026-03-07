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

## 1. Clonar o Projeto

### macOS e Linux

Abra o Terminal e execute:

```bash
git clone https://github.com/fzampirolli/LLMv02-PI-1q.git
cd LLMv02-PI-1q
```

### Windows

Instale o [Git para Windows](https://git-scm.com/download/win) se ainda não tiver.  
Abra o **Git Bash** (recomendado) ou o PowerShell e execute:

```bash
git clone https://github.com/fzampirolli/LLMv02-PI-1q.git
cd LLMv02-PI-1q
```

> **Recomendação para Windows:** use o **Git Bash** (instalado com o Git) para todos os comandos deste guia. O `runProva1q.sh` requer bash — no PowerShell use o caminho alternativo indicado na seção de execução.

---

## 2. Pré-requisitos

### Python 3.8+

| Sistema | Verificar versão | Instalar |
|---|---|---|
| macOS | `python3 --version` | [python.org](https://www.python.org/downloads/) ou `brew install python` |
| Linux | `python3 --version` | `sudo apt install python3` (Debian/Ubuntu) |
| Windows | `python --version` | [python.org](https://www.python.org/downloads/) — marque **"Add to PATH"** na instalação |

### Instalar dependências Python

**macOS / Linux:**
```bash
pip3 install aiohttp pyyaml
```

**Windows (PowerShell ou Git Bash):**
```bash
pip install aiohttp pyyaml
```

Se houver erro de permissão no Linux/macOS:
```bash
pip3 install aiohttp pyyaml --break-system-packages
```

### Chave de API Groq (gratuita)

1. Acesse [console.groq.com](https://console.groq.com) e crie uma conta
2. Vá em **API Keys** → **Create API Key**
3. Copie a chave (começa com `gsk_...`) — você usará no `config.yaml`

---

## 3. Configuração Inicial

### Copiar o template de configuração

**macOS / Linux / Git Bash:**
```bash
cp config.yaml.example config.yaml
```

**Windows (PowerShell):**
```powershell
Copy-Item config.yaml.example config.yaml
```

### Editar o config.yaml

Abra o `config.yaml` em qualquer editor de texto e preencha os campos obrigatórios:

```yaml
# Chave da API Groq (obrigatório)
groq:
  api_key: "gsk_..."          # cole sua chave aqui

# Credenciais de e-mail SMTP (só necessário para enviar feedbacks)
email:
  smtp_server: smtp.ufabc.edu.br
  smtp_port: 587
  from_address: seu_email@ufabc.edu.br
  password: "sua_senha"

# Configuração da prova
grading:
  weights:
    q1: 100                   # pontuação máxima da questão
  prompt_file: "prompt1q.txt"

# Pasta com as submissões dos alunos
paths:
  student_base_dir: "Simulado0"
```

> ⚠️ **Nunca versione o `config.yaml`** — ele contém sua API key e senha de e-mail.  
> Ele já está listado no `.gitignore` do projeto.

### Criar o prompt da questão

Edite o arquivo `prompt1q.txt` com as instruções para a IA e o enunciado completo da questão. Exemplo de estrutura:

```
Você é um professor corretor. Avalie o código Python abaixo segundo os critérios:

Critério 1 - Entrada e Tipagem (máx: 10 pts): ...
Critério 2 - Lógica de Validação e Cálculo (máx: 60 pts): ...
Critério 3 - Saída Formatada (máx: 30 pts): ...

Ao final, escreva obrigatoriamente uma linha no formato:
Nota: X + Y + Z = TOTAL/100
```

> A linha no formato `X + Y + Z = TOTAL/100` ou `= TOTAL pontos` é usada pelo sistema  
> para extrair a nota automaticamente e exibi-la no resumo comparativo. Portanto, não deve ser alterada.

---

## 4. Baixar as Submissões do Moodle VPL

1. Acesse a atividade **VPL** no Moodle
2. Clique em **Lista de envios**
3. Na tabela de alunos, localize a **seta para baixo** (⬇) no **canto direito do cabeçalho** da tabela — fica bem discreta
4. Clique em **Baixar envios** ou **Baixar todos os envios**  
   — o Moodle já inclui apenas a **última submissão** de cada aluno
5. Descompacte o arquivo `.zip` baixado
6. Mova a pasta descompactada para dentro do projeto:

**macOS / Linux:**
```bash
mv ~/Downloads/Simulado0 ./Simulado0
```

**Windows (PowerShell):**
```powershell
Move-Item "$env:USERPROFILE\Downloads\Simulado0" .\Simulado0
```

**Windows (Git Bash):**
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

### Renomear pastas

Se os nomes das pastas vierem em formato diferente de `Nome Sobrenome - login`, use o script de renomeação antes de prosseguir:

```bash
bash renomear_pastas.sh Simulado0
```

---

## 5. Executar a Validação com IA

### macOS / Linux

```bash
chmod +x runProva1q.sh
./runProva1q.sh Simulado0
```

### Windows — Git Bash

```bash
bash runProva1q.sh Simulado0
```

### Windows — PowerShell (alternativa sem bash)

```powershell
python grader1q.py Simulado0 config.yaml --max-concurrent 3
```

### Opções disponíveis

```
./runProva1q.sh <pasta_alunos> [config.yaml] [--max-concurrent N]
```

| Parâmetro | Padrão | Descrição |
|---|---|---|
| `pasta_alunos` | — | Pasta com as submissões (obrigatório) |
| `config.yaml` | `config.yaml` | Arquivo de configuração |
| `--max-concurrent N` | `3` | Chamadas simultâneas à API Groq |

Exemplos:
```bash
./runProva1q.sh Simulado0
./runProva1q.sh Simulado0 config.yaml
./runProva1q.sh Simulado0 config.yaml --max-concurrent 5
```

### O que acontece durante a execução

1. Valida o ambiente (Python, dependências, arquivos)
2. Para cada aluno, localiza a **última submissão** (pasta com o timestamp mais recente no nome)
3. Envia o código + prompt para a API Groq de forma **assíncrona** — todos os alunos são processados em paralelo, respeitando o limite de concorrência
4. Se um modelo LLM falhar, tenta automaticamente o próximo da lista com backoff exponencial
5. Só grava o `rubrica.txt` se a LLM retornar uma resposta válida
6. Consolida todos os resultados em `Simulado0_ALL.txt`

### Saída gerada

Após a execução, cada aluno terá:

```
Simulado0/Nome Aluno - login/TIMESTAMP/rubrica.txt
```

E o consolidado geral:

```
Simulado0_ALL.txt
```

Para visualizar todos os resultados:

```bash
# macOS / Linux / Git Bash
cat Simulado0_ALL.txt | less

# Windows (PowerShell)
Get-Content Simulado0_ALL.txt | more
```

---

## 6. Estrutura do rubrica.txt

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

## 7. Envio de Feedbacks por E-mail (Opcional)

O script `enviar_email.py` envia o `rubrica.txt` como anexo para cada aluno no endereço `login@aluno.ufabc.edu.br`.

### Configuração

1. Preencha a seção `email:` no `config.yaml` com suas credenciais SMTP. 
2. Prencha na seção `templates:` no mesmo arquivo:
   - `assunto` — personalize conforme a prova
   - `corpo: |` - ajuste nome da disciplina e os detalhes desse feedback por IA.

### Teste antes de enviar para os alunos

Na linha 138 do script, o endereço está redirecionado para um e-mail de teste:

```python
email_destino = 'fzampirolli@gmail.com'   # TESTE — comente para produção
```

Antes de disparar para todos os alunos, rode com seu próprio e-mail para validar o conteúdo. Quando estiver satisfeito, comente essa linha para que o sistema use o endereço real de cada aluno.

### Executar

**macOS / Linux / Git Bash:**
```bash
python3 enviar_email.py
```

**Windows (PowerShell):**
```powershell
python enviar_email.py
```

> ⚠️ **Atenção:** O e-mail enviado aos alunos deixa explícito que a correção é gerada por IA  
> e pode conter imprecisões. **A nota oficial sempre é a atribuída pelo professor no Moodle.**

---

## 8. Modelos LLM Disponíveis

Configurados em `config.yaml` na seção `groq.models`. O sistema tenta cada modelo em ordem e passa para o próximo em caso de falha:

| Modelo | Observação |
|---|---|
| `llama-3.3-70b-versatile` | Melhor qualidade geral |
| `openai/gpt-oss-120b` | Alta capacidade |
| `llama-3.1-8b-instant` | Mais rápido, menor qualidade |
| `openai/gpt-oss-20b` | Rápido |

O plano gratuito do Groq permite **30 requisições por minuto**. Consulte os limites atuais em [console.groq.com/settings/limits](https://console.groq.com/settings/limits).

---

## 9. Solução de Problemas

**`❌ Execute com bash: bash runProva1q.sh`**  
No macOS/Linux execute `bash runProva1q.sh Simulado0`.  
No Windows use Git Bash ou chame diretamente: `python grader1q.py Simulado0`.

**Nota Moodle aparece como `0.00` ou `N/A`**  
Verifique se existe `TIMESTAMP.ceg/execution.txt` na pasta do aluno.  
O sistema extrai a nota do padrão `Grade :=>>100` nesse arquivo.

**Nota da IA aparece como `?`**  
A resposta da IA não contém uma linha de nota reconhecível.  
Revise o `prompt1q.txt` e instrua explicitamente a IA a escrever:
```
Nota: X + Y + Z = TOTAL/100
```

**Erro HTTP 400 (`max_tokens`)**  
O `max_response_chars` no `config.yaml` excede o limite da Groq.  
O sistema já limita automaticamente a 8192 tokens — não é necessário ajustar.

**Nenhum arquivo de código encontrado**  
Extensões suportadas: `.py`, `.java`, `.c`, `.cpp`, `.js`, `.ts`.  
Verifique se os arquivos estão diretamente dentro da pasta de timestamp, não em subpastas.

**Windows: `python3` não reconhecido**  
No Windows o comando é `python` (sem o `3`). Use `python grader1q.py ...` diretamente.

---

## 10. Privacidade — O que é enviado à API Groq

A cada correção, o sistema envia à API Groq **apenas dois campos**:

| Campo | Conteúdo | Dado pessoal? |
|---|---|---|
| `system` | Conteúdo do `prompt1q.txt` (enunciado + critérios) | ❌ Não |
| `user` | Nome do arquivo + código-fonte do aluno | ❌ Não |

**Nunca são enviados:** nome do aluno, e-mail, login, RA, CPF, turma ou qualquer outro metadado. Esses dados existem apenas como nomes de pastas locais e nunca são incluídos na requisição HTTP.

O trecho abaixo reproduz exatamente o payload que trafega para a API (ver `llm_interface_prova.py`, método `_single_call`):

```json
{
  "model": "llama-3.3-70b-versatile",
  "messages": [
    {
      "role": "system",
      "content": "Você é um professor corretor. Avalie o código Python abaixo segundo os critérios:\n\nCritério 1 - Entrada e Tipagem (máx: 10 pts): ...\nCritério 2 - Lógica de Validação e Cálculo (máx: 60 pts): ...\nCritério 3 - Saída Formatada (máx: 30 pts): ...\n\nAo final, escreva obrigatoriamente:\nNota: X + Y + Z = TOTAL/100"
    },
    {
      "role": "user",
      "content": "# ==================== solucao.py ====================\nangulo = float(input())\ndistancia = float(input())\n\nif angulo > 0 and angulo < 90 and distancia > 0:\n    c = (360/angulo)*distancia\n    print(f\"Circunferencia estimada: {c:.2f} km\")\nelif angulo == 0:\n    print(\"ERRO: Angulo zero impede o calculo.\")\n..."
    }
  ],
  "temperature": 0.7,
  "max_tokens": 8192,
  "stream": false
}
```

> ⚠️ **Única ressalva:** se o professor incluir dados identificadores dentro do próprio `prompt1q.txt` (ex: nome de aluno no enunciado), esses dados serão transmitidos. O enunciado da questão normalmente não contém esse tipo de informação.

---

## 11. Segurança

O `config.yaml` contém sua API key e senha de e-mail. Ele já está no `.gitignore` do projeto, mas certifique-se de que o seu também contenha:

```
config.yaml
*.env
logs/
*_ALL.txt
```

Nunca compartilhe nem publique o `config.yaml`.