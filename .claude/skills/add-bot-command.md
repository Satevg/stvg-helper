# Add a New Bot Command

Commands are slash commands triggered by the user typing e.g. `/mycommand`.

## Steps

1. **Add a handler function** in `bot/handler.py`:
   ```python
   async def mycommand_command(update: Update, context: Any) -> None:
       assert update.message is not None
       await update.message.reply_text("Your response here.")
   ```

2. **Register the handler** in `build_application()`:
   ```python
   application.add_handler(CommandHandler("mycommand", mycommand_command))
   ```

## Checklist
- [ ] Handler added with correct type annotations (`Update`, `Any`, `-> None`)
- [ ] Handler registered in `build_application()`
- [ ] `make lint` passes
- [ ] `make release` to deploy