#!/usr/bin/env python3
import sys
import re
import csv
from pathlib import Path


def extrair_dados(arquivo):

    alunos = []

    nome = None
    login = None
    moodle = None
    ia = None

    with open(arquivo, encoding="utf-8") as f:
        for linha in f:

            # novo aluno
            m = re.search(r"ALUNO:\s*(.+?)\s*-\s*([A-Za-z0-9_]+)", linha)
            if m:
                # salva anterior somente se tiver nota
                if nome and (moodle is not None or ia is not None):
                    alunos.append([nome, login, moodle, ia])

                nome = m.group(1).strip()
                login = m.group(2).strip()
                moodle = None
                ia = None
                continue

            # nota Moodle
            m = re.search(r"Moodle\s*:.*?([\d\.]+)\s*/\s*100", linha)
            if m:
                moodle = float(m.group(1))

            # nota IA
            m = re.search(r"IA\s*:?\s*(\d+)\s*/\s*100", linha)
            if m:
                ia = int(m.group(1))

    # último aluno
    if nome and (moodle is not None or ia is not None):
        alunos.append([nome, login, moodle, ia])

    return alunos


def main():

    if len(sys.argv) != 2:
        print("Uso: python3 gerar_relatorio.py arquivo.txt")
        sys.exit(1)

    entrada = sys.argv[1]
    base = Path(entrada).stem
    saida = base + ".csv"

    alunos = extrair_dados(entrada)

    with open(saida, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["nome", "login", "nota_moodle", "nota_ia"])
        writer.writerows(alunos)

    print(f"{len(alunos)} alunos exportados")
    print(f"CSV gerado: {saida}")


if __name__ == "__main__":
    main()