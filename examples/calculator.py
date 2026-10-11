def add(a, b):
    return a + b


def subtract(a, b):
    return a - b


def multiply(a, b):
    return a * b


def divide(a, b):
    if b == 0:
        raise ValueError("Tidak bisa membagi dengan nol.")
    return a / b


def get_number(prompt):
    while True:
        try:
            return float(input(prompt))
        except ValueError:
            print("Masukkan angka yang valid.")


def calculate(choice, a, b):
    if choice == "1":
        return add(a, b)
    if choice == "2":
        return subtract(a, b)
    if choice == "3":
        return multiply(a, b)
    if choice == "4":
        return divide(a, b)
    raise ValueError("Pilihan tidak valid.")


def main():
    menu = """
=== Kalkulator Sederhana ===
1. Tambah
2. Kurang
3. Kali
4. Bagi
5. Keluar
"""

    while True:
        print(menu)
        choice = input("Pilih operasi (1-5): ").strip()

        if choice == "5":
            print("Terima kasih sudah menggunakan kalkulator.")
            break

        if choice not in {"1", "2", "3", "4"}:
            print("Pilihan tidak valid. Silakan pilih 1 sampai 5.")
            continue

        first_number = get_number("Masukkan angka pertama: ")
        second_number = get_number("Masukkan angka kedua: ")

        try:
            result = calculate(choice, first_number, second_number)
            print(f"Hasil: {result}")
        except ValueError as error:
            print(error)


if __name__ == "__main__":
    main()
