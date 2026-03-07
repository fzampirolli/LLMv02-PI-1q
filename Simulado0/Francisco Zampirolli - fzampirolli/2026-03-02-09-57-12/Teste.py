theta=float(input())
distancia=float(input())

if theta==0:
    print("ERRO: Angulo zero impede o calculo.")

elif theta < 0 or theta >= 90:
    print("ERRO: Angulo invalido.")

elif distancia <=0:
    print("ERRO: Distancia Invalida.")

else:
    circunferencia = (360 / theta)
    print(f"Circunferencia estimada:{circunferencia:.2f} km")