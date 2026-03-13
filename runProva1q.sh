#!/usr/bin/env bash
# =============================================================================
# runProva1q.sh — Correção assíncrona de provas (1 questão única)
# =============================================================================
# Guarda de segurança: garante bash (não sh/dash/zsh)
[ -z "${BASH_VERSION:-}" ] && { echo "❌ Execute com bash: bash $0 $*" >&2; exit 1; }
# Uso:
#     ./renomear_pastas.sh <pasta_dos_alunos>
#     ./runProva1q.sh <pasta_dos_alunos> [config.yaml] [--max-concurrent N]
#
# Exemplos:
#     ./runProva1q.sh Simulado0
#     ./runProva1q.sh Simulado0 config.yaml
#     ./runProva1q.sh Simulado0 config.yaml --max-concurrent 5
#
# Estrutura esperada:
#   Simulado0/
#   ├── Nome Aluno - usuario/
#   │   ├── 2026-03-04-10-14-39/          ← pasta de submissão (timestamp)
#   │   │   └── solucao.py                ← qualquer nome (.py .java .c ...)
#   │   └── 2026-03-04-10-14-39.ceg/
#   │       └── execution.txt             ← resultado do Moodle (opcional)
#   └── ...
#
# Arquivos lidos no diretório corrente:
#   config.yaml    — configurações (API key, modelos, pesos, prompt_file …)
#   prompt1q.txt   — system prompt base (campo grading.prompt_file no YAML)
#
# Saída por aluno:
#   Simulado0/<Nome>/TIMESTAMP/rubrica.txt
#
# Consolidado final:
#   Simulado0_ALL.txt
#   Simulado0_ALL.csv
#
# Diferencial em relação ao runProva2q.sh:
#   - Chamadas assíncronas via Python/aiohttp (sem sleep fixo entre alunos)
#   - Concorrência controlada por Semaphore (--max-concurrent)
#   - Sem loop sequencial em shell — Python orquestra tudo
# =============================================================================

set -euo pipefail

# =============================================================================
# CORES
# =============================================================================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m'

print_info()    { echo -e "${BLUE}ℹ${NC} $1"; }
print_success() { echo -e "${GREEN}✓${NC} $1"; }
print_warning() { echo -e "${YELLOW}⚠${NC} $1"; }
print_error()   { echo -e "${RED}✗${NC} $1" >&2; }
print_section() { echo -e "${MAGENTA}▶${NC} $1"; }
print_step()    { echo -e "  ${CYAN}→${NC} $1"; }

# =============================================================================
# LOCK — evita execuções paralelas acidentais
# =============================================================================
LOCK_DIR="/tmp/runProva1q.lock.d"

cleanup() {
    rm -rf "$LOCK_DIR" 2>/dev/null || true
}
trap cleanup EXIT

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    PID_FILE="$LOCK_DIR/PID"
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            print_error "Já existe uma instância em execução (PID: $PID)."
            print_step  "Aguarde ou remova: rm -rf \"$LOCK_DIR\""
            exit 1
        else
            print_warning "Lock órfão detectado (PID $PID). Limpando..."
            rm -rf "$LOCK_DIR"
            mkdir "$LOCK_DIR"
        fi
    else
        print_error "Lock corrompido. Remova: rm -rf \"$LOCK_DIR\""
        exit 1
    fi
fi
echo $$ > "$LOCK_DIR/PID"

# =============================================================================
# ARGUMENTOS
# =============================================================================

BASE_STUDENT_DIR=""
CONFIG_FILE="config.yaml"
MAX_CONCURRENT=3

show_help() {
    echo ""
    echo -e "${BLUE}Uso:${NC} $0 <pasta_dos_alunos> [config.yaml] [--max-concurrent N]"
    echo ""
    echo -e "${MAGENTA}Argumentos posicionais:${NC}"
    echo "  <pasta_dos_alunos>    Diretório raiz com submissões dos alunos (obrigatório)"
    echo "  [config.yaml]         Arquivo de configuração (padrão: config.yaml)"
    echo ""
    echo -e "${MAGENTA}Opções:${NC}"
    echo "  --max-concurrent N    Chamadas simultâneas à API (padrão: 3)"
    echo "  --help                Exibe esta ajuda"
    echo ""
    echo -e "${MAGENTA}Exemplos:${NC}"
    echo "  ${GREEN}./runProva1q.sh Simulado0${NC}"
    echo "  ${GREEN}./runProva1q.sh Simulado0 config.yaml --max-concurrent 5${NC}"
    echo ""
}

# Parse de argumentos (posicionais + opções)
POS=0
while [[ $# -gt 0 ]]; do
    case $1 in
        --max-concurrent)
            MAX_CONCURRENT="$2"
            shift 2
            ;;
        --help|-h)
            show_help
            exit 0
            ;;
        --*)
            print_error "Opção desconhecida: $1"
            show_help
            exit 1
            ;;
        *)
            case $POS in
                0) BASE_STUDENT_DIR="$1" ;;
                1) CONFIG_FILE="$1" ;;
                *) print_error "Argumento extra inesperado: $1"; exit 1 ;;
            esac
            POS=$((POS + 1))
            shift
            ;;
    esac
done

if [ -z "$BASE_STUDENT_DIR" ]; then
    print_error "Informe a pasta dos alunos."
    show_help
    exit 1
fi

# =============================================================================
# VALIDAÇÕES INICIAIS
# =============================================================================

print_section "Validando ambiente..."

# Python 3.8+
if ! command -v python3 &>/dev/null; then
    print_error "Python 3 não encontrado."
    exit 1
fi

# Verifica versão mínima via Python (funciona em macOS e Linux)
if ! python3 -c "import sys; assert sys.version_info >= (3,8)" 2>/dev/null; then
    PY_VER=$(python3 --version 2>&1 | cut -d' ' -f2)
    print_error "Python 3.8+ necessário (encontrado: $PY_VER)"
    exit 1
fi
PY_VER=$(python3 --version | cut -d' ' -f2)
print_success "Python $PY_VER OK"

# Diretório de alunos
if [ ! -d "$BASE_STUDENT_DIR" ]; then
    print_error "Diretório não encontrado: $BASE_STUDENT_DIR"
    exit 1
fi
print_success "Pasta de alunos: $BASE_STUDENT_DIR"

# Config YAML
if [ ! -f "$CONFIG_FILE" ]; then
    print_error "config.yaml não encontrado: $CONFIG_FILE"
    exit 1
fi
print_success "Config: $CONFIG_FILE"

# Módulos Python necessários
print_section "Verificando dependências Python..."
MISSING_DEPS=()
for dep in aiohttp yaml; do
    if ! python3 -c "import $dep" 2>/dev/null; then
        MISSING_DEPS+=("$dep")
    fi
done

if [ ${#MISSING_DEPS[@]} -gt 0 ]; then
    print_error "Dependências faltando: ${MISSING_DEPS[*]}"
    echo ""
    echo "  Instale com:"
    echo "    pip install aiohttp pyyaml"
    echo "  ou, em sistemas com restrição:"
    echo "    pip install aiohttp pyyaml --break-system-packages"
    exit 1
fi
print_success "aiohttp e pyyaml OK"

# grader1q.py, llm_interface_prova.py e gerar_relatorio.py
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
GRADER="$SCRIPT_DIR/grader1q.py"
LLM_IFACE="$SCRIPT_DIR/llm_interface_prova.py"
RELATORIO="$SCRIPT_DIR/gerar_relatorio.py"  # FIX 4: validação adicionada

if [ ! -f "$GRADER" ]; then
    print_error "grader1q.py não encontrado em: $SCRIPT_DIR"
    exit 1
fi
if [ ! -f "$LLM_IFACE" ]; then
    print_error "llm_interface_prova.py não encontrado em: $SCRIPT_DIR"
    exit 1
fi
if [ ! -f "$RELATORIO" ]; then  # FIX 4: valida antes de precisar
    print_error "gerar_relatorio.py não encontrado em: $SCRIPT_DIR"
    exit 1
fi
print_success "grader1q.py, llm_interface_prova.py e gerar_relatorio.py OK"

# prompt_file (lê do YAML com awk)
PROMPT_FILE=$(awk '/^[[:space:]]*prompt_file:/{
    gsub(/^[[:space:]]*prompt_file:[[:space:]]*/,"");
    gsub(/["\047]/,""); gsub(/[[:space:]]*#.*/,""); print; exit
}' "$CONFIG_FILE")
PROMPT_FILE="${PROMPT_FILE:-prompt1q.txt}"

if [ ! -f "$PROMPT_FILE" ]; then
    print_error "Arquivo de prompt não encontrado: $PROMPT_FILE"
    print_step  "Crie '$PROMPT_FILE' com as instruções para a IA."
    exit 1
fi
print_success "Prompt: $PROMPT_FILE"

# =============================================================================
# BANNER E RESUMO
# =============================================================================

echo ""
echo -e "${BLUE}"
cat << "EOF"
╔═══════════════════════════════════════════════════════╗
║      Correção Automática de Provas — 1 Questão        ║
║              Versão Assíncrona (aiohttp)              ║
╚═══════════════════════════════════════════════════════╝
EOF
echo -e "${NC}"

print_section "Configuração de Execução"
echo ""
echo "  Pasta de alunos : $BASE_STUDENT_DIR"
echo "  Config          : $CONFIG_FILE"
echo "  Prompt          : $PROMPT_FILE"
echo "  Max Concurrent  : $MAX_CONCURRENT chamadas simultâneas"
echo ""

# =============================================================================
# EXECUÇÃO
# =============================================================================

mkdir -p logs
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="logs/prova1q_${TIMESTAMP}.log"

print_section "Iniciando correção assíncrona..."
echo ""

python3 -u "$GRADER" \
    "$BASE_STUDENT_DIR" \
    "$CONFIG_FILE" \
    --max-concurrent "$MAX_CONCURRENT" \
    2>&1 | tee "$LOG_FILE"

EXIT_CODE=${PIPESTATUS[0]}

# FIX 3: consolidação só ocorre se o grader terminou com sucesso
if [ $EXIT_CODE -eq 0 ]; then
    # FIX 2: glob seguro com nullglob — não aborta se não houver arquivos
    shopt -s nullglob
    RUBRICAS=("${BASE_STUDENT_DIR}"/*/*/rubrica.txt)
    shopt -u nullglob

    if [ ${#RUBRICAS[@]} -gt 0 ]; then
        cat "${RUBRICAS[@]}" > "${BASE_STUDENT_DIR}_ALL.txt"
        # FIX 1: removido `-c` incorreto — python3 <arquivo>, não python3 -c <arquivo>
        python3 "$RELATORIO" "${BASE_STUDENT_DIR}_ALL.txt" > "${BASE_STUDENT_DIR}_ALL.csv"
    else
        print_warning "Nenhum rubrica.txt encontrado para consolidar."
    fi
fi

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    print_success "Correção concluída com sucesso!"
    print_step    "Log salvo em: $LOG_FILE"
    print_step    "Consolidado : ${BASE_STUDENT_DIR}_ALL.txt"
    print_step    "Relatório   : ${BASE_STUDENT_DIR}_ALL.csv"
elif [ $EXIT_CODE -eq 130 ]; then
    print_warning "Interrompido pelo usuário (Ctrl+C)."
else
    print_error   "Finalizado com erros (código: $EXIT_CODE)."
    echo ""
    echo "  Últimas linhas do log:"
    tail -n 10 "$LOG_FILE" | sed 's/^/    /'
fi

exit $EXIT_CODE