import random


CHOICES = {
    "1": "batu",
    "2": "gunting",
    "3": "kertas",
}

WIN_RULES = {
    "batu": "gunting",
    "gunting": "kertas",
    "kertas": "batu",
}


def get_player_choice():
    while True:
        print("\nPilih gerakan:")
        print("1. Batu")
        print("2. Gunting")
        print("3. Kertas")
        print("4. Keluar")

        choice = input("Masukkan pilihan (1-4): ").strip()

        if choice == "4":
            return None

        if choice in CHOICES:
            return CHOICES[choice]

        print("Pilihan tidak valid. Silakan pilih 1 sampai 4.")


def get_winner(player_choice, computer_choice):
    if player_choice == computer_choice:
        return "seri"

    if WIN_RULES[player_choice] == computer_choice:
        return "pemain"

    return "komputer"


def print_round_result(player_choice, computer_choice, winner):
    print(f"\nKamu memilih     : {player_choice}")
    print(f"Komputer memilih : {computer_choice}")

    if winner == "seri":
        print("Hasil: Seri!")
    elif winner == "pemain":
        print("Hasil: Kamu menang!")
    else:
        print("Hasil: Komputer menang!")


def main():
    score = {
        "pemain": 0,
        "komputer": 0,
        "seri": 0,
    }

    print("=== Game Batu Gunting Kertas ===")

    while True:
        player_choice = get_player_choice()

        if player_choice is None:
            print("\n=== Skor Akhir ===")
            print(f"Kamu     : {score['pemain']}")
            print(f"Komputer : {score['komputer']}")
            print(f"Seri     : {score['seri']}")
            print("Terima kasih sudah bermain.")
            break

        computer_choice = random.choice(list(WIN_RULES.keys()))
        winner = get_winner(player_choice, computer_choice)
        score[winner] += 1

        print_round_result(player_choice, computer_choice, winner)


if __name__ == "__main__":
    main()
