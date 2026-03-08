#!/usr/bin/env python3
"""
Sistema de Correção Automática de Provas — 1 Questão
Arquivo: grader1q.py

Orquestra a correção assíncrona de todos os alunos:
  1. Lê config.yaml
  2. Carrega prompt1q.txt (system prompt)
  3. Descobre submissões em BASE_STUDENT_DIR
  4. Envia ao LLM em paralelo (Semaphore controlado)
  5. Grava rubrica.txt por aluno
  6. Consolida tudo em <BASE_STUDENT_DIR>_ALL.txt

Uso:
    python3 grader1q.py <pasta_dos_alunos> [config.yaml] [--max-concurrent N]
"""

import argparse
import asyncio
import logging
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

# Importa o cliente LLM adaptado para provas
from llm_interface_prova import LLMClientProva, LLMResponse, process_students_async

# =============================================================================
# LOGGING
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# =============================================================================
# DESENHO DE CAIXAS (mesma estética do runProva2q.sh)
# =============================================================================

_W = 55

def _line_top() -> str:
    return "┌" + "─" * _W + "┐"

def _line_bot() -> str:
    return "└" + "─" * _W + "┘"

def _line_h() -> str:
    return "├" + "─" * _W + "┤"

def _irow(text: str) -> str:
    inner = _W - 2
    return f"│  {text[:inner]:<{inner}}│"

def _irow_sep() -> str:
    return "│  " + "─" * (_W - 4) + "  │"


def box(lines: List[str]) -> str:
    """Envolve linhas em uma caixa simples."""
    rows = [_line_top()]
    for l in lines:
        rows.append(_irow(l))
    rows.append(_line_bot())
    return "\n".join(rows)


# =============================================================================
# EXTRAÇÃO DE NOTAS (heurística robusta — mesma lógica do runProva2q.sh)
# =============================================================================

def extrair_nota_texto(texto: str, q_weight: int = 100) -> str:
    """
    Extrai a nota final do texto livre retornado pela IA.
    Estratégias em ordem de confiabilidade:

      S0a: soma com texto entre parcelas  "10 (Critério 1) + 60 (...) = 100 pontos"
      S0b: soma limpa                     "10 + 40 + 30 = 80"
      S1 : barra sobre peso               "= 60/100"
      S2 : "Nota final" + N/peso (3 linhas)
      S3 : qualquer "N/peso"
      S4 : "Nota Final: N pontos" ou "Total: N pontos"
      S5 : "→ N pontos"
      S6 : último número plausível ≤ q_weight
    """
    # S0a: soma com texto arbitrário entre parcelas, terminando em "= N"
    m = re.search(
        r'[0-9]+(?:[^+\n=]*\+[^+\n=]*[0-9]+)+\s*=\s*([0-9]+(?:[.,][0-9]+)?)',
        texto, re.IGNORECASE
    )
    if m:
        val = float(m.group(1).replace(',', '.'))
        if 0 < val <= q_weight:
            return m.group(1).replace(',', '.')

    # S0b: soma limpa "X + Y + ... = N"
    m = re.search(
        r'[0-9]+(?:\s*\+\s*[0-9]+)+\s*=\s*([0-9]+(?:[.,][0-9]+)?)',
        texto, re.IGNORECASE
    )
    if m:
        val = float(m.group(1).replace(',', '.'))
        if 0 < val <= q_weight:
            return m.group(1).replace(',', '.')

    # S1: "= N/peso"
    m = re.search(
        r'=\s*([0-9]+(?:[.,][0-9]+)?)\s*/\s*' + str(q_weight),
        texto, re.IGNORECASE
    )
    if m:
        return m.group(1).replace(',', '.')

    # S2: "Nota final" seguida de N/peso em até 3 linhas
    m = re.search(
        r'nota\s+final[^\n]*\n(?:[^\n]*\n){0,3}[^\n]*?([0-9]+(?:[.,][0-9]+)?)\s*/\s*' + str(q_weight),
        texto, re.IGNORECASE | re.DOTALL
    )
    if m:
        return m.group(1).replace(',', '.')

    # S3: qualquer "N/peso"
    m = re.search(
        r'([0-9]+(?:[.,][0-9]+)?)\s*/\s*' + str(q_weight),
        texto, re.IGNORECASE
    )
    if m:
        val = float(m.group(1).replace(',', '.'))
        if 0 <= val <= q_weight:
            return m.group(1).replace(',', '.')

    # S4: "Nota Final: N pontos" ou "Total: N pontos"
    m = re.search(
        r'(?:nota\s*final|total)[^:\n→]*[:\→]\s*([0-9]+(?:[.,][0-9]+)?)\s*pontos',
        texto, re.IGNORECASE
    )
    if m:
        val = float(m.group(1).replace(',', '.'))
        if 0 < val <= q_weight:
            return m.group(1).replace(',', '.')

    # S5: "→ N pontos"
    m = re.search(r'[→>]\s*([0-9]+(?:[.,][0-9]+)?)\s*pontos', texto, re.IGNORECASE)
    if m:
        val = float(m.group(1).replace(',', '.'))
        if 0 < val <= q_weight:
            return m.group(1).replace(',', '.')

    # S6: último número plausível ≤ q_weight
    nums = re.findall(r'\b([0-9]+(?:[.,][0-9]+)?)\b', texto)
    for n in reversed(nums):
        try:
            val = float(n.replace(',', '.'))
            if 0 < val <= q_weight:
                return n.replace(',', '.')
        except ValueError:
            continue

    return "?"


def limpar_resposta(texto: str) -> str:
    """Remove markdown e seções de dica/sugestão desnecessárias."""
    # Remove blocos de código markdown
    texto = re.sub(r'```.*?```', '', texto, flags=re.DOTALL)
    # Remove negrito markdown
    texto = texto.replace('**', '')
    # Remove seções de sugestão após as notas
    texto = re.sub(
        r'\n(Dica|Sugest|Revis|Let me know|Here[^ ]).+',
        '', texto, flags=re.DOTALL | re.IGNORECASE
    )
    return texto.strip()


# =============================================================================
# DESCOBERTA DE ARQUIVOS DE SUBMISSÃO
# =============================================================================

SUPPORTED_EXTENSIONS = ['py', 'java', 'c', 'cpp', 'js', 'r']


def encontrar_submissao(student_dir: Path) -> Optional[Tuple[Path, Path]]:
    """
    Retorna (submission_dir, code_file) para a submissão mais recente do aluno.
    Ordena pelo NOME da pasta (formato timestamp YYYY-MM-DD-HH-MM-SS),
    mais confiável que mtime em macOS/rsync. Ignora pastas *.ceg.
    """
    subs = sorted(
        [d for d in student_dir.iterdir() if d.is_dir() and not d.name.endswith('.ceg')],
        key=lambda d: d.name,
        reverse=True,
    )
    if not subs:
        return None

    submission_dir = subs[0]

    # Procura arquivo de código (qualquer extensão suportada, exceto rubrica)
    for ext in SUPPORTED_EXTENSIONS:
        for f in submission_dir.glob(f'*.{ext}'):
            if 'rubrica' not in f.name.lower():
                return submission_dir, f

    return None


def extrair_notas_moodle(student_dir: Path, submission_dir: Path) -> Tuple[str, str]:
    """
    Extrai nota da correção automática do Moodle do execution.txt.
    Suporta dois formatos:
      - "Grade :=>>100"  ou  "Grade :=>> 85.5"   (Moodle VPL)
      - "(85.50%)"                                 (formato percentual)
    Retorna (nota_str, ceg_path) onde nota_str é 0–100 (percentual).
    """
    ceg_path = submission_dir.parent / (submission_dir.name + '.ceg') / 'execution.txt'
    if not ceg_path.exists():
        return "N/A", "N/A"

    text = ceg_path.read_text(errors='ignore')

    # Padrão principal: "Grade :=>> 100"  ou  "Grade :=>>85.5"
    m = re.search(r'Grade\s*:=+>>\s*([0-9]+(?:[.,][0-9]+)?)', text, re.IGNORECASE)
    if m:
        return m.group(1).replace(',', '.'), ceg_path

    # Fallback: "(85.50%)"
    m = re.search(r'\(([0-9]+(?:\.[0-9]+)?)%\)', text)
    if m:
        return m.group(1), ceg_path

    return "0.00", ceg_path


# =============================================================================
# GERAÇÃO DA RUBRICA
# =============================================================================

def gerar_rubrica(
    student_name: str,
    submission_dir: Path,
    code_file: Path,
    response: LLMResponse,
    moodle_percent: str,
    moodle_exec_path,
    q_weight: int,
    config: Dict,
) -> str:
    """Monta o conteúdo completo do rubrica.txt para um aluno."""
    from datetime import datetime

    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    lines = []

    # ── Cabeçalho ────────────────────────────────────────────────────────────
    lines.append(box([
        f" ALUNO: {student_name}",
        f" DATA : {timestamp}",
    ]))
    lines.append("")

    # ── Correção Moodle ───────────────────────────────────────────────────────
    moodle_section = [" CORRECAO AUTOMATICA - MOODLE", _line_h()]
    if moodle_percent != "N/A":
        try:
            nota_abs = float(moodle_percent) * q_weight / 100
            moodle_section.append(
                f" Questão: {moodle_percent}% (peso {q_weight}pts)  ->  {nota_abs:.2f} / {q_weight} pontos"
            )
        except ValueError:
            moodle_section.append(f" Questão: {moodle_percent}%")
    else:
        moodle_section.append(" CORRECAO DO MOODLE NAO DISPONIVEL")

    lines.append(_line_top())
    for seg in moodle_section:
        if seg == _line_h():
            lines.append(seg)
        else:
            lines.append(_irow(seg))
    lines.append(_line_bot())
    lines.append("")

    # ── Enunciado / competências ──────────────────────────────────────────────
    lines.append(_line_top())
    lines.append(_irow(" CODIGO SUBMETIDO"))
    lines.append(_line_h())
    code_text = code_file.read_text(errors='replace')
    lines.append(code_text)
    lines.append(_line_bot())
    lines.append("")

    # ── Avaliação da IA ───────────────────────────────────────────────────────
    if response.success and response.content:
        content_clean = limpar_resposta(response.content)
        nota_ia = extrair_nota_texto(content_clean, q_weight)

        lines.append(_line_top())
        lines.append(_irow(" AVALIACAO DA IA"))
        lines.append(_line_h())
        lines.append(_irow(f"Modelo   : {response.model_used}"))
        lines.append(_irow(f"Timestamp: {timestamp}"))
        lines.append(_irow(f"Duração  : {response.duration_seconds:.2f}s"))
        lines.append(_line_bot())
        lines.append("")
        lines.append(content_clean)
        lines.append("")

        # ── Resumo comparativo ────────────────────────────────────────────────
        lines.append(_line_top())
        lines.append(_irow(" RESUMO — MOODLE  x  IA"))
        lines.append(_line_h())
        lines.append(_irow(f" Peso da questão : {q_weight} pontos"))
        lines.append(_irow_sep())

        # Nota Moodle
        if moodle_percent not in ("N/A", "0.00", None):
            try:
                nota_moodle_abs = float(moodle_percent) * q_weight / 100
                lines.append(_irow(f" Moodle : {moodle_percent}%  →  {nota_moodle_abs:.2f} / {q_weight} pts"))
            except ValueError:
                lines.append(_irow(f" Moodle : {moodle_percent}"))
        else:
            lines.append(_irow(f" Moodle : {moodle_percent}"))

        # Nota IA
        lines.append(_irow(f" IA     : {nota_ia} / {q_weight} pts"))

        # Diferença, se ambas disponíveis
        if moodle_percent not in ("N/A", None) and nota_ia != "?":
            try:
                nm = float(moodle_percent) * q_weight / 100
                ni = float(nota_ia)
                diff = ni - nm
                sinal = "+" if diff >= 0 else ""
                lines.append(_irow_sep())
                lines.append(_irow(f" Diferença (IA - Moodle): {sinal}{diff:.2f} pts"))
            except ValueError:
                pass

        lines.append(_line_bot())

    else:
        lines.append(_line_top())
        lines.append(_irow(" AVALIACAO DA IA - FALHA"))
        lines.append(_line_h())
        lines.append(_irow(f" Erro: {response.error or 'desconhecido'}"))
        lines.append(_line_bot())

    lines.append("")

    # ── Log bruto do Moodle ───────────────────────────────────────────────────
    if moodle_exec_path and isinstance(moodle_exec_path, Path) and moodle_exec_path.exists():
        lines.append(_line_top())
        lines.append(_irow(" LOG BRUTO - CORRECAO DO MOODLE"))
        lines.append(_line_h())
        lines.append(moodle_exec_path.read_text(errors='replace'))
        lines.append(_line_bot())
        lines.append("")

    # ── Rodapé ───────────────────────────────────────────────────────────────
    lines.append(box([f" ALUNO: {student_name}"]))

    return "\n".join(lines)


# =============================================================================
# ORQUESTRADOR PRINCIPAL
# =============================================================================

async def run(
    base_dir: Path,
    config: Dict,
    system_prompt: str,
    max_concurrent: int,
    min_code_lines: int,
    q_weight: int,
    rubric_output: str,
):
    """Descobre alunos, monta tasks, executa em paralelo e grava resultados."""

    student_dirs = sorted([d for d in base_dir.iterdir() if d.is_dir()])
    if not student_dirs:
        logger.error(f"Nenhuma pasta de aluno encontrada em: {base_dir}")
        sys.exit(1)

    logger.info(f"🎓 {len(student_dirs)} aluno(s) encontrado(s)")

    # ── Monta lista de tasks ──────────────────────────────────────────────────
    tasks: List[Tuple[str, str, Dict]] = []
    skipped = []

    for sdir in student_dirs:
        student_name = sdir.name
        result = encontrar_submissao(sdir)

        if result is None:
            logger.warning(f"  ⚠  {student_name}: nenhum arquivo de código. Pulando.")
            skipped.append(student_name)
            continue

        submission_dir, code_file = result

        # === NOVA ALTERAÇÃO: Pular se rubrica já existir ===
        rpath = submission_dir / rubric_output
        if rpath.exists():
            logger.info(f"  ⏭  {student_name}: rubrica já existe. Pulando LLM.")
            # Opcional: se quiser que ele apareça no consolidado final mesmo pulando, 
            # seria necessário ler o arquivo existente. Caso contrário, ele apenas pula.
            continue 
        # ===================================================
        
        code_text = code_file.read_text(errors='replace')
        num_lines = len(code_text.splitlines())

        if num_lines < min_code_lines:
            logger.warning(
                f"  ⚠  {student_name}: código muito curto ({num_lines} linhas, "
                f"mínimo {min_code_lines}). Pulando."
            )
            skipped.append(student_name)
            continue

        ext = code_file.suffix.lstrip('.')
        sep = "//" if ext in ('java', 'c', 'cpp', 'js', 'ts') else "#"
        code_content = (
            f"{sep} ==================== {code_file.name} ====================\n"
            f"{code_text}"
        )

        metadata = {
            'student': student_name,
            'student_dir': sdir,
            'submission_dir': submission_dir,
            'code_file': code_file,
        }
        tasks.append((system_prompt, code_content, metadata))

    if not tasks:
        logger.error("Nenhuma submissão válida para processar.")
        sys.exit(1)

    logger.info(f"📋 {len(tasks)} submissão(ões) válida(s) | concorrência: {max_concurrent}")
    logger.info("🚀 Iniciando correção assíncrona...\n")

    # ── Executa em paralelo ───────────────────────────────────────────────────
    async with LLMClientProva(config) as client:
        results = await process_students_async(client, tasks, max_concurrent)

    # ── Grava rubrica.txt por aluno ───────────────────────────────────────────
    all_rubricas = []

    for metadata, response in results:
        student_name   = metadata['student']
        student_dir    = metadata['student_dir']
        submission_dir = metadata['submission_dir']
        code_file      = metadata['code_file']

        # Não grava rubrica se a LLM não retornou nada
        if not response.success or not response.content:
            logger.warning(f"  ⚠  {student_name}: sem retorno da LLM — rubrica.txt NÃO gerada.")
            continue

        moodle_percent, moodle_exec_path = extrair_notas_moodle(student_dir, submission_dir)

        rubrica_text = gerar_rubrica(
            student_name=student_name,
            submission_dir=submission_dir,
            code_file=code_file,
            response=response,
            moodle_percent=moodle_percent,
            moodle_exec_path=moodle_exec_path,
            q_weight=q_weight,
            config=config,
        )

        rubrica_path = submission_dir / rubric_output
        rubrica_path.write_text(rubrica_text, encoding='utf-8')

        status = "✅" if response.success else "❌"
        logger.info(f"  {status} {student_name} → {rubrica_path}")
        all_rubricas.append(rubrica_text)

    # ── Consolida tudo ────────────────────────────────────────────────────────
    consolidado_path = base_dir.parent / f"{base_dir.name}_ALL.txt"
    separator = "\n" + "=" * 80 + "\n"
    consolidado_path.write_text(separator.join(all_rubricas), encoding='utf-8')

    logger.info(f"\n🎉 Concluído! {len(results)} aluno(s) processado(s).")
    if skipped:
        logger.info(f"   Pulados: {', '.join(skipped)}")
    logger.info(f"   Consolidado: {consolidado_path}")


# =============================================================================
# ENTRY POINT
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Correção assíncrona de provas — 1 questão"
    )
    parser.add_argument("base_dir",       help="Pasta raiz das submissões (ex: p1moodle)")
    parser.add_argument("config",         nargs='?', default="config.yaml",
                        help="Arquivo de configuração (padrão: config.yaml)")
    parser.add_argument("--max-concurrent", type=int, default=3,
                        help="Máximo de chamadas paralelas à API (padrão: 3)")
    args = parser.parse_args()

    # ── Valida caminhos ───────────────────────────────────────────────────────
    base_dir = Path(args.base_dir)
    if not base_dir.is_dir():
        print(f"❌ Diretório não encontrado: {base_dir}")
        sys.exit(1)

    config_path = Path(args.config)
    if not config_path.is_file():
        print(f"❌ Config não encontrado: {config_path}")
        sys.exit(1)

    # ── Carrega config ────────────────────────────────────────────────────────
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    grading = config.get('grading', {})
    min_code_lines = grading.get('min_code_lines', 4)
    q_weight       = grading.get('weights', {}).get('q1', 100)
    rubric_output  = config.get('paths', {}).get('output_rubric_filename', 'rubrica.txt')
    prompt_file    = grading.get('prompt_file', 'prompt1q.txt')

    # ── Carrega prompt ────────────────────────────────────────────────────────
    prompt_path = Path(prompt_file)
    if not prompt_path.is_file():
        print(f"❌ Arquivo de prompt não encontrado: {prompt_path}")
        sys.exit(1)

    system_prompt = prompt_path.read_text(encoding='utf-8')

    # ── Resumo de execução ────────────────────────────────────────────────────
    masked_key = ""
    api_key = config.get('groq', {}).get('api_key', '')
    if api_key:
        masked_key = api_key[:7] + "..." + api_key[-4:]

    models = config.get('groq', {}).get('models', [])

    print(f"  Peso Q1    : {q_weight} pontos")
    print(f"  Concorrente: {args.max_concurrent} chamadas simultâneas")
    print(f"  API Key    : {masked_key}")
    print(f"  Modelos    : {', '.join(models)}")
    print()

    # ── Executa ───────────────────────────────────────────────────────────────
    asyncio.run(run(
        base_dir=base_dir,
        config=config,
        system_prompt=system_prompt,
        max_concurrent=args.max_concurrent,
        min_code_lines=min_code_lines,
        q_weight=q_weight,
        rubric_output=rubric_output,
    ))


if __name__ == "__main__":
    main()