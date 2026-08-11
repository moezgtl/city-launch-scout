# Setting up the MCP Server

This lets you scout venues by just talking to Claude Desktop —
no Terminal commands needed after setup.

---

## Step 1 — Install the MCP library

Open Terminal, go to your project folder, then run:

```bash
pip3 install "mcp[cli]"
```

---

## Step 2 — Find your project's full path

In Terminal, inside the project folder, run:

```bash
pwd
```

You'll see something like:
```
/Users/moezgritli/Desktop/city-launch-scout
```

Copy that. You'll need it in the next step.

---

## Step 3 — Install Claude Desktop

Download it from: https://claude.ai/download

Install it and sign in with your Claude account.

---

## Step 4 — Configure Claude Desktop

Open Terminal and run this (it creates the config file):

```bash
mkdir -p ~/.claude
open -e ~/.claude/claude_desktop_config.json
```

If the file is empty, paste this in — replacing the path with YOUR path from Step 2:

```json
{
  "mcpServers": {
    "city-launch-scout": {
      "command": "python3",
      "args": ["/Users/moezgritli/Desktop/city-launch-scout/mcp_server/server.py"]
    }
  }
}
```

Save and close.

---

## Step 5 — Restart Claude Desktop

Quit Claude Desktop completely (Cmd+Q), then reopen it.

To check the server connected: click the 🔌 icon in the bottom left of the
chat window. You should see "city-launch-scout" listed.

---

## Step 6 — Use it

Now just type in Claude Desktop:

> "Scout restaurants in Oberkampf, Paris, France.
>  The coordinates are 48.8640, 2.3690"

Claude will run the full pipeline and show you the results directly
in the conversation.

Other things you can say:
- "Show me my previous scout runs"
- "What was shortlisted in my last run?"
- "Scout venues in Shoreditch, London — coordinates 51.5227, -0.0782"

---

## If it doesn't work

- Make sure the path in the config file is exactly right (copy from `pwd`)
- Make sure Claude Desktop was fully restarted after editing the config
- Make sure `mcp[cli]` is installed (`pip3 install "mcp[cli]"`)
- Check that your `.env` file has both API keys filled in
