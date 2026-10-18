
const form = document.getElementById("chat-form");
const input = document.getElementById("message-input");
const messages = document.getElementById("messages");
const statusText = document.getElementById("chat-status");
const sendButton = document.getElementById("send-button");

let historyLoaded = false;
let isSending = false;



function addMessage(text, role) {
    const bubble = document.createElement("div");
    bubble.className =
        `message ${role === "user" ? "user" : "assistant"}`;

    if (role === "user") {
        bubble.textContent = text;
    } else {
        const escapeHTML = (value) =>
            String(value ?? "").replace(/[&<>"']/g, char => ({
                "&": "&amp;",
                "<": "&lt;",
                ">": "&gt;",
                '"': "&quot;",
                "'": "&#39;"
            })[char]);

        let html = escapeHTML(text);

        const codeBlocks = [];
        html = html.replace(/```(\w*)\n([\s\S]*?)```/g,
            (_, language, code) => {
                codeBlocks.push(
                    `<pre><code>${code.trimEnd()}</code></pre>`
                );
                return `CODEBLOCKPLACEHOLDER${codeBlocks.length - 1}END`;
            }
        );

        html = html
            .replace(/^### (.+)$/gm, "<h3>$1</h3>")
            .replace(/^## (.+)$/gm, "<h2>$1</h2>")
            .replace(/^# (.+)$/gm, "<h1>$1</h1>")
            .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
            .replace(/__(.+?)__/g, "<strong>$1</strong>")
            .replace(/\*([^*\n]+)\*/g, "<em>$1</em>")
            .replace(/`([^`\n]+)`/g, "<code>$1</code>")
            .replace(/^\s*[-*] (.+)$/gm, "<li>$1</li>")
            .replace(/(?:<li>.*<\/li>\n?)+/g,
                list => `<ul>${list}</ul>`)
            .replace(/\n/g, "<br>");

        html = html.replace(
            /CODEBLOCKPLACEHOLDER(\d+)END/g,
            (_, index) => codeBlocks[Number(index)]
        );

        bubble.innerHTML = html;
    }

    messages.appendChild(bubble);
    messages.scrollTop = messages.scrollHeight;
}



function showWelcome() {
    addMessage(
        "Hello! I'm your SMS Student AI assistant. What would you like to learn today?",
        "assistant"
    );
}

async function loadHistory() {
    if (historyLoaded) return;

    historyLoaded = true;
    statusText.textContent = "Loading previous conversations...";

    try {
        const response = await fetch("/api/chat/history", {
            headers: { "Accept": "application/json" }
        });

        if (!response.ok) {
            throw new Error("Could not load chat history.");
        }

        const data = await response.json();

        // Only clear messages after history has loaded successfully.
        messages.replaceChildren();

        if (Array.isArray(data.messages) && data.messages.length > 0) {
            data.messages.forEach((item) => {
                addMessage(item.message, item.role);
            });
        } else {
            showWelcome();
        }

        statusText.textContent = "";
    } catch (error) {
        historyLoaded = false;
        statusText.textContent =
            "Previous history could not be loaded. Refresh to try again.";
    }
}

form.addEventListener("submit", async (event) => {
    event.preventDefault();

    if (isSending) return;

    const message = input.value.trim();
    if (!message) return;

    isSending = true;
    addMessage(message, "user");

    input.value = "";
    input.disabled = true;
    sendButton.disabled = true;
    statusText.textContent = "Thinking...";

    try {
        const response = await fetch("/api/chat", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Accept": "application/json"
            },
            body: JSON.stringify({ message })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || "The request failed.");
        }

        addMessage(data.reply, "assistant");
        statusText.textContent = "";
    } catch (error) {
        statusText.textContent =
            error.message || "Unable to contact the assistant.";
    } finally {
        isSending = false;
        input.disabled = false;
        sendButton.disabled = false;
        input.focus();
    }
});

loadHistory();
