# Add an Item to the Bot Menu

The bot uses a reply keyboard defined as `MAIN_MENU` in `bot/handler.py`.

## Steps

1. **Add the button** to `MAIN_MENU` in `bot/handler.py`:
   ```python
   MAIN_MENU = ReplyKeyboardMarkup(
       [[KeyboardButton("Hello"), KeyboardButton("Bye"), KeyboardButton("NewItem")]],
       resize_keyboard=True,
   )
   ```
   Buttons can be arranged across multiple rows — each inner list is a row:
   ```python
   [
       [KeyboardButton("Hello"), KeyboardButton("Bye")],
       [KeyboardButton("NewItem")],
   ]
   ```

2. **Handle the button press** by adding the label to the `filters.Text` list and adding a branch in `menu_button_handler`:
   ```python
   application.add_handler(
       MessageHandler(filters.Text(["Hello", "Bye", "NewItem"]), menu_button_handler)
   )
   ```
   ```python
   async def menu_button_handler(update: Update, context: Any) -> None:
       assert update.message is not None
       text = update.message.text
       if text == "Hello":
           await update.message.reply_text("Hello there!")
       elif text == "Bye":
           await update.message.reply_text("Goodbye! See you later.")
       elif text == "NewItem":
           await update.message.reply_text("Your response here.")
   ```

## Checklist
- [ ] Button added to `MAIN_MENU`
- [ ] Label added to `filters.Text([...])`
- [ ] Branch added in `menu_button_handler`
- [ ] `make lint` passes
- [ ] `make release` to deploy