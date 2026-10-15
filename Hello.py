import tkinter as tk
from tkinter import ttk


COLOR_DESCRIPTIONS = {
    "Red": "You are bold, energetic, and ready to take action.",
    "Blue": "You are calm, thoughtful, and someone others can rely on.",
    "Green": "You are balanced, kind, and enjoy helping things grow.",
    "Yellow": "You are cheerful, optimistic, and full of bright ideas.",
    "Purple": "You are imaginative, curious, and wonderfully original.",
    "Orange": "You are friendly, adventurous, and bring energy wherever you go.",
}


def main():
    root = tk.Tk()
    root.title("Your Favorite Color")
    root.resizable(False, False)

    selected_color = tk.StringVar(value="")
    description = tk.StringVar(value="Choose a color to see what it suggests about you.")

    def show_description():
        color = selected_color.get()
        if color:
            description.set(COLOR_DESCRIPTIONS[color])
        else:
            description.set("Choose a color to see what it suggests about you.")

    frame = ttk.Frame(root, padding=20)
    frame.pack(fill="both", expand=True)

    ttk.Label(frame, text="What is your favorite color?").pack(anchor="w", pady=(0, 8))

    for color in COLOR_DESCRIPTIONS:
        ttk.Radiobutton(
            frame,
            text=color,
            value=color,
            variable=selected_color,
            command=show_description,
        ).pack(anchor="w")

    ttk.Label(
        frame,
        textvariable=description,
        wraplength=320,
        justify="left",
    ).pack(anchor="w", pady=(16, 0))

    root.mainloop()


if __name__ == "__main__":
    main()