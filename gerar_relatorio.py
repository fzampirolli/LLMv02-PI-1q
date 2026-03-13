import re
import csv
import os
import sys


def extrair_dados(caminho_arquivo):

    with open(caminho_arquivo, 'r', encoding='utf-8') as f:
        conteudo = f.read()

    # Separa blocos por aluno usando o cabeçalho "ALUNO:"
    # FIX 1: separador original (═{10,}) não funciona para 1 questão;
    #         o bloco de cada aluno vai de um "ALUNO:" até o próximo.
    blocos = re.split(r'(?=┌[─]+┐\s*\n│\s*ALUNO\s*:)', conteudo)

    lista_alunos = []

    for bloco in blocos:

        if "ALUNO" not in bloco:
            continue

        # FIX 2: regex de identificação estava correto, mantido
        match_id = re.search(r'ALUNO\s*:\s*(.*?)\s*-\s*([^\s│]*)', bloco)
        if not match_id:
            continue

        # FIX 8: ignora blocos de rodapé (apenas cabeçalho sem seção RESUMO)
        if "RESUMO" not in bloco:
            continue

        nome  = match_id.group(1).strip()
        login = match_id.group(2).strip()

        # FIX 3: padrão Moodle corrigido para o formato real:
        #   │   Questão: 30% (peso 100pts)  ->  30.00 / 100 pontos  │
        moodle_match = re.search(
            r'Questão\s*:\s*([\d.]+)%\s*\(peso\s*([\d]+)pts\)'
            r'\s*->\s*([\d.]+)\s*/\s*([\d]+)\s*pontos',
            bloco
        )

        # FIX 4: padrão IA corrigido para o formato real:
        #   │   IA     : 68 / 100 pts   │
        ia_match = re.search(
            r'│\s*IA\s*:\s*([\d.]+)\s*/\s*([\d]+)\s*pts',
            bloco
        )

        # FIX 5: padrão diferença corrigido para o formato real:
        #   │   Diferença (IA - Moodle): +38.00 pts   │
        diff_match = re.search(
            r'Diferença\s*\(IA - Moodle\)\s*:\s*([+-]?[\d.]+)\s*pts',
            bloco
        )

        nota_moodle = float(moodle_match.group(3)) if moodle_match else 0.0
        peso        = int(moodle_match.group(4))   if moodle_match else 100
        nota_ia     = float(ia_match.group(1))     if ia_match     else 0.0
        diferenca   = float(diff_match.group(1))   if diff_match   else (nota_ia - nota_moodle)

        lista_alunos.append({
            "Nome":         nome,
            "Login":        login,
            "Peso":         peso,
            "Nota_Moodle":  f"{nota_moodle:.2f}",
            "Nota_IA":      f"{nota_ia:.2f}",
            "Diferenca":    f"{diferenca:+.2f}",
        })

    lista_alunos.sort(key=lambda x: x["Nome"])

    return lista_alunos


def salvar_csv(dados, arquivo_saida):

    # FIX 6: cabeçalho atualizado para refletir estrutura de 1 questão
    header = [
        "Nome",
        "Login",
        "Peso",
        "Nota_Moodle",
        "Nota_IA",
        "Diferenca",
    ]

    with open(arquivo_saida, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=header, lineterminator="\n")
        writer.writeheader()
        writer.writerows(dados)


if __name__ == "__main__":

    if len(sys.argv) != 2:
        print("Uso: python3 gerar_relatorio.py arquivo.txt", file=sys.stderr)
        sys.exit(1)

    entrada = sys.argv[1]

    if not os.path.isfile(entrada):
        print(f"❌ Arquivo não encontrado: {entrada}", file=sys.stderr)
        sys.exit(1)

    # FIX 7: nome do CSV gerado automaticamente a partir do .txt
    base  = os.path.splitext(entrada)[0]
    saida = base + ".csv"

    dados = extrair_dados(entrada)

    if not dados:
        print("⚠️  Nenhum aluno encontrado. Verifique o formato do arquivo.", file=sys.stderr)
        sys.exit(1)

    salvar_csv(dados, saida)

    print(f"✅ {len(dados)} aluno(s) exportado(s) para {saida}", file=sys.stderr)