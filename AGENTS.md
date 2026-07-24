# Release Safety Rules

When publishing this repository to npm, finish all prepublish validation before requesting any OTP
from the user.

Required release order:

1. Run the exact deterministic prepublish validation and wait for it to finish successfully.
2. Only after validation succeeds, ask the user for an OTP.
3. Start `npm publish` only when the OTP is fresh enough to be consumed immediately.
4. If the publish session expires or prompts again, never restart a long validation step after
   taking a fresh OTP unless validation inputs changed.

Never ask for an OTP while `prepublishOnly` or any equivalent validation is still pending.
