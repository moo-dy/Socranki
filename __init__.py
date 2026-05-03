from aqt import mw, gui_hooks
from aqt.qt import *
from aqt.webview import AnkiWebView
from anki.utils import strip_html
import urllib.request
import urllib.error
import json
import re
import time
import random

SOCRATIC_ANGLES = [
    "Focus on a practical real-world application of this concept.",
    "Focus on a theoretical 'what-if' scenario that challenges the concept.",
    "Focus on a common misconception or a subtle edge case.",
    "Focus on the underlying 'why' rather than the 'how'.",
    "Focus on how this concept relates to or contradicts other fields of study.",
    "Focus on a comparative analysis with a related but different concept.",
    "Focus on the historical or etymological origin to deepen understanding.",
    "Focus on a visual or metaphorical way to think about this concept."
]

# Global references for our UI elements
socratic_dock = None
socratic_text_edit = None
socratic_button = None
socratic_input = None
socratic_action_button = None

current_hidden_answer = ""
current_ai_question = ""
current_context = ""
chat_history_html = ""
is_generating = False

def render_socratic_content(content: str, append: bool = False):
    """Renders text as HTML in the AnkiWebView, ensuring MathJax support."""
    global chat_history_html
    
    # Basic markdown-ish formatting
    formatted = content.replace("\n", "<br>")
    # Simple bolding **text** -> <b>text</b>
    formatted = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", formatted)
    
    new_block = f"<div style='margin-bottom: 10px;'>{formatted}</div>"
    
    if append:
        chat_history_html += "<hr style='border: 0; border-top: 1px solid #444; margin: 10px 0;'>" + new_block
    else:
        chat_history_html = new_block
        
    # Wrap in Anki's standard CSS for dark mode compatibility
    full_html = f"""
    <html>
    <head>
        <style>
            body {{ 
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                font-size: 14px; 
                line-height: 1.5;
                color: #d7d7d7;
                background-color: #2c2c2c;
                padding: 10px;
            }}
            b {{ color: #007aff; }}
            hr {{ border-color: #444; }}
        </style>
    </head>
    <body>
        {chat_history_html}
    </body>
    </html>
    """
    
    # mw.prepare_card_text_for_display handles MathJax \[ \] and \( \)
    final_html = mw.prepare_card_text_for_display(full_html)
    socratic_text_edit.setHtml(final_html)

def fetch_ai_response(system_prompt: str, user_prompt: str, config: dict) -> str:
    backend_type = config.get("backend_type", "ollama")
    api_key = config.get("api_key", "")
    model_name = config.get("model_name", "")
    
    if backend_type == "ollama":
        if not model_name:
            model_name = "phi3"
        url = "http://localhost:11434/api/chat"
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "stream": False,
            "options": {"temperature": 1.0}
        }
        headers = {"Content-Type": "application/json"}
    elif backend_type == "openai":
        if not model_name:
            model_name = "gpt-4o-mini"
        custom_url = config.get("custom_api_url", "").strip()
        url = custom_url if custom_url else "https://api.openai.com/v1/chat/completions"
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "stream": False,
            "temperature": 1.0
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
    elif backend_type == "gemini":
        if not model_name:
            model_name = "gemini-1.5-flash"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        combined_prompt = f"{system_prompt}\n\n{user_prompt}"
        payload = {
            "contents": [{"parts": [{"text": combined_prompt}]}],
            "generationConfig": {"temperature": 1.0}
        }
        headers = {"Content-Type": "application/json"}
    else:
        return f"Error: Unknown backend_type '{backend_type}'"
        
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers=headers, method='POST')
    
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode('utf-8'))
            if backend_type == "ollama":
                return result.get("message", {}).get("content", "")
            elif backend_type == "gemini":
                try:
                    return result["candidates"][0]["content"]["parts"][0]["text"]
                except (KeyError, IndexError):
                    return f"Error: Unexpected Gemini response format: {json.dumps(result)}"
            else:
                return result.get("choices", [{}])[0].get("message", {}).get("content", "")
    except urllib.error.HTTPError as e:
        try:
            error_body = e.read().decode('utf-8')
            return f"HTTP Error {e.code}: {e.reason}\nDetails: {error_body}"
        except Exception:
            return f"HTTP Error {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        return f"Network Error: {str(e.reason)}"
    except Exception as e:
        return f"Error: {str(e)}"

def get_contextual_knowledge(current_card) -> str:
    """Fetches up to 5 related notes based on explicit NID links, tags, or deck."""
    if not current_card:
        return ""
        
    current_note = current_card.note()
    tags = current_note.tags
    deck_id = current_card.did
    
    seen_nids = set()
    seen_nids.add(current_note.id)
    
    context_strings = []
    
    # Helper to clean and add note content
    def add_note_to_context(note, source_label=""):
        fields = note.values()
        f_raw = fields[0] if len(fields) > 0 else ""
        b_raw = fields[1] if len(fields) > 1 else ""
        
        f_clean = " ".join(strip_html(f_raw).strip().split())
        b_clean = " ".join(strip_html(b_raw).strip().split())
        
        if f_clean or b_clean:
            context_strings.append(f"[{source_label} Note]: Front: {f_clean} | Back: {b_clean}")
            seen_nids.add(note.id)

    # 1. Search for explicit nid links in the current note
    note_text = " ".join(current_note.values())
    explicit_nids = re.findall(r'nid[:\s]*(\d+)', note_text)
    
    print(f"[Socranki Debug] Detected {len(explicit_nids)} NID references: {explicit_nids}")
    
    for nid_str in explicit_nids:
        if len(context_strings) >= 5:
            break
        try:
            nid = int(nid_str)
            if nid not in seen_nids:
                # Try to get note by ID
                rel_note = mw.col.get_note(nid)
                if rel_note:
                    add_note_to_context(rel_note, "Linked")
                    print(f"[Socranki Debug] Successfully linked note {nid}")
                else:
                    print(f"[Socranki Debug] Note {nid} not found in collection.")
        except Exception as e:
            print(f"[Socranki Debug] Failed to fetch linked note {nid_str}: {str(e)}")
            continue
            
    # 2. Search for Backlinks (notes pointing to THIS note)
    if len(context_strings) < 5:
        backlink_query = f"nid{current_note.id}"
        backlink_nids = mw.col.find_notes(backlink_query)
        for bnid in backlink_nids:
            if len(context_strings) >= 5:
                break
            if bnid not in seen_nids:
                try:
                    rel_note = mw.col.get_note(bnid)
                    add_note_to_context(rel_note, "Backlink")
                    print(f"[Socranki Debug] Successfully found backlink: {bnid}")
                except Exception:
                    continue

    # 3. Search by tags or deck
    query_parts = []
    query_parts.append(f"-cid:{current_card.id}")
    
    if tags:
        tag_query = " OR ".join([f"tag:{t}" for t in tags])
        query_parts.append(f"({tag_query})")
    else:
        deck_name = mw.col.decks.name(deck_id)
        query_parts.append(f'"deck:{deck_name}"')
        
    query = " ".join(query_parts)
    related_cids = mw.col.find_cards(query)
    
    # 3. Process related cards ensuring unique notes
    for cid in related_cids:
        if len(context_strings) >= 5:
            break
        try:
            rel_card = mw.col.get_card(cid)
            if rel_card.nid not in seen_nids:
                rel_note = rel_card.note()
                add_note_to_context(rel_note, "Related")
        except Exception:
            continue
            
    if not context_strings:
        return ""
        
    return "Contextual Knowledge:\n" + "\n".join(context_strings)

def get_bloom_prompt(card) -> tuple[str, str]:
    """Determines Bloom's Taxonomy level based on card scheduling metadata."""
    card_type = card.type
    ivl = card.ivl
    
    if card_type in [0, 1, 3]:
        level_name = "Understanding"
        system_prompt = "Based on the concept, ask the user to explain it simply or summarize the core mechanism in their own words."
    elif card_type == 2 and ivl < 21:
        level_name = "Applying"
        system_prompt = "Invent a brief, novel real-world scenario. Ask the user how this concept applies to solve the scenario."
    else: # card_type == 2 and ivl >= 21
        level_name = "Analyzing"
        system_prompt = "Using the card context and related knowledge, ask a question that forces the user to compare/contrast this concept, or identify a flaw in a related argument."
        
    return level_name, system_prompt

def on_generate_clicked():
    """Extracts card text and displays it in the UI and console."""
    if not mw.reviewer.card:
        return
        
    global current_hidden_answer, current_ai_question, current_context, is_generating
    note = mw.reviewer.card.note()
    fields = note.values()
    
    # Attempt to grab the first two fields safely (usually Front and Back)
    front_raw = fields[0] if len(fields) > 0 else ""
    back_raw = fields[1] if len(fields) > 1 else ""
    
    # Clean HTML formatting
    front_text = strip_html(front_raw).strip()
    back_text = strip_html(back_raw).strip()
    
    output = f"--- Front ---\n{front_text}\n\n--- Back ---\n{back_text}"
    
    # Phase 3: Fetch related contextual knowledge
    context_knowledge = get_contextual_knowledge(mw.reviewer.card)
    if context_knowledge:
        output += f"\n\n--- Context ---\n{context_knowledge}"
    # Phase 4: Bloom's Taxonomy Logic
    bloom_level, bloom_prompt = get_bloom_prompt(mw.reviewer.card)
    print(f"\n[Socratic Anki] Bloom's Level Detected: {bloom_level}")
    config = mw.addonManager.getConfig(__name__) or {}
    mode = config.get("interaction_mode", "chit_chat")
    
    target_lang = config.get("target_language", "auto").strip()
    if not target_lang or target_lang.lower() == "auto":
        lang_instruction = "Respond in the same language as the flashcard content."
    else:
        lang_instruction = f"Respond in {target_lang}."
    
    angle = random.choice(SOCRATIC_ANGLES)
    variation_instruction = f"Be creative and approach the topic from this angle: {angle} Avoid repeating previous questions."
    
    # Phase 5: Assembly
    if mode == "one_liner":
        system_prompt = (
            f"You are a Socratic tutor. {lang_instruction} {variation_instruction} You primarily ask follow-up questions to deepen understanding. You provide a single follow-up question and its ideal answer in the exact format:\n"
            "QUESTION: [your question here]\n"
            "ANSWER: [the ideal answer here]\n"
            f"{bloom_prompt}"
        )
    else:
        system_prompt = (
            f"You are a Socratic tutor. {lang_instruction} {variation_instruction} You primarily ask one short, single follow-up question. Never give the answer immediately in the first turn, but be encouraging.\n"
            f"{bloom_prompt}"
        )
    
    user_prompt = (
        f"Current Card Front: {front_text}\n"
        f"Current Card Back: {back_text}\n"
    )
    if context_knowledge:
        user_prompt += f"\nRelated Knowledge:\n{context_knowledge}"
        
    # Inject a unique nonce to force LLM variance
    nonce = int(time.time() * 1000)
    user_prompt += f"\n\n[Variation Seed: {nonce}]"
    # noice    
    current_context = user_prompt
        
    # Also print to Anki's debug console / terminal
    print("\n[Socranki] System Prompt:")
    print(system_prompt)
    print("\n[Socranki] User Prompt:")
    print(user_prompt)
    
    socratic_button.setEnabled(False)
    render_socratic_content(f"<i>Generating {bloom_level} question...</i>")
    if socratic_input: socratic_input.hide()
    if socratic_action_button: socratic_action_button.hide()
    
    is_generating = True
        
    def background_task():
        return fetch_ai_response(system_prompt, user_prompt, config)
        
    def on_done(future):
        global is_generating, current_hidden_answer, current_ai_question
        socratic_button.setEnabled(True)
        try:
            result = future.result()
            if mode == "one_liner":
                q_part = result
                a_part = ""
                if "ANSWER:" in result:
                    parts = result.split("ANSWER:")
                    q_part = parts[0].replace("QUESTION:", "").strip()
                    a_part = parts[1].strip()
                elif "Answer:" in result:
                    parts = result.split("Answer:")
                    q_part = parts[0].replace("Question:", "").strip()
                    a_part = parts[1].strip()
                
                global current_hidden_answer
                current_hidden_answer = a_part
                render_socratic_content(q_part)
                
                socratic_action_button.setText("Show Answer")
                socratic_action_button.show()
            else:
                global current_ai_question
                current_ai_question = result
                render_socratic_content(result)
                
                socratic_input.clear()
                socratic_input.show()
                socratic_action_button.setText("Submit Answer")
                socratic_action_button.show()
                
            is_generating = False
                
        except Exception as e:
            is_generating = False
            render_socratic_content(f"<b>Task Failed:</b> {str(e)}")
            
    mw.taskman.run_in_background(background_task, on_done)

def on_action_clicked():
    global current_hidden_answer, current_ai_question, current_context
    config = mw.addonManager.getConfig(__name__) or {}
    mode = config.get("interaction_mode", "chit_chat")
    
    if mode == "one_liner":
        render_socratic_content(f"<b>Ideal Answer:</b><br>{current_hidden_answer}", append=True)
        socratic_action_button.hide()
        
    elif mode == "chit_chat":
        user_answer = socratic_input.text().strip()
        if not user_answer:
            return
            
        socratic_action_button.setEnabled(False)
        socratic_input.setEnabled(False)
        render_socratic_content(f"<b>You:</b> {user_answer}<br><i>[Evaluating...]</i>", append=True)
        
        target_lang = config.get("target_language", "auto").strip()
        if not target_lang or target_lang.lower() == "auto":
            lang_instruction = "Respond in the same language as the flashcard content."
        else:
            lang_instruction = f"Respond in {target_lang}."
            
        system_prompt = (
            f"The user has provided an answer to your previous Socratic question. {lang_instruction} "
            "Evaluate it based on the flashcard context. Be encouraging but correct any misconceptions. Keep it brief. "
            "If the user asks for help, says they don't know, or seems genuinely stuck after an attempt, you should provide a hint or the full answer to maintain learning momentum."
        )
        
        eval_prompt = (
            f"Context:\n{current_context}\n\n"
            f"Your Question: {current_ai_question}\n\n"
            f"User Answer: {user_answer}"
        )
        
        def background_eval():
            return fetch_ai_response(system_prompt, eval_prompt, config)
            
        def on_eval_done(future):
            socratic_action_button.setEnabled(True)
            socratic_input.setEnabled(True)
            socratic_input.clear()
            try:
                result = future.result()
                render_socratic_content(f"<b>Tutor:</b> {result}", append=True)
            except Exception as e:
                render_socratic_content(f"<b>Task Failed:</b> {str(e)}", append=True)
                
        mw.taskman.run_in_background(background_eval, on_eval_done)

def setup_ui():
    """Initializes the UI elements as a dockable, resizable widget."""
    global socratic_dock, socratic_text_edit, socratic_button, socratic_input, socratic_action_button
    
    if socratic_dock is not None:
        return
        
    socratic_dock = QDockWidget("Socranki", mw)
    socratic_dock.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
    socratic_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable | QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetFloatable)
    
    container = QWidget()
    layout = QVBoxLayout()
    layout.setContentsMargins(5, 5, 5, 5)
    
    # Initialize button
    socratic_button = QPushButton("Generate follow-up question")
    socratic_button.clicked.connect(on_generate_clicked)
    
    # Initialize web view
    socratic_text_edit = AnkiWebView()
    render_socratic_content("<i>Socratic question will appear here...</i>")
    
    socratic_input = QLineEdit()
    socratic_input.setPlaceholderText("Type your answer here...")
    socratic_input.returnPressed.connect(on_action_clicked)
    socratic_input.hide()
    
    socratic_action_button = QPushButton("Action")
    socratic_action_button.clicked.connect(on_action_clicked)
    socratic_action_button.hide()
    
    layout.addWidget(socratic_button)
    layout.addWidget(socratic_text_edit)
    layout.addWidget(socratic_input)
    layout.addWidget(socratic_action_button)
    container.setLayout(layout)
    
    socratic_dock.setWidget(container)
    socratic_dock.hide()
    
    # Apply a matte, cleaner style to the dock title bar
    socratic_dock.setStyleSheet("""
        QDockWidget::title {
            background-color: #2c2c2c;
            text-align: left;
            padding-left: 10px;
            font-size: 12px;
            font-weight: bold;
            color: #d7d7d7;
            border-top: 1px solid #3a3a3a;
        }
    """)
    
    # Add to Anki's main window at the bottom
    mw.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, socratic_dock)

def on_show_answer():
    """Triggered when the back of the card is revealed."""
    if socratic_dock:
        config = mw.addonManager.getConfig(__name__) or {}
        is_auto = config.get("auto_generate", False)
        
        socratic_dock.show()
        
        # Only clear if we aren't auto-generating (since auto-gen already started on the front)
        if not is_auto:
            render_socratic_content("<i>Thinking...</i>")
        
        if socratic_button:
            if is_auto:
                socratic_button.hide()
            else:
                socratic_button.show()
                socratic_button.setEnabled(True)
        
        if socratic_input:
            # Only hide if we are still waiting for the AI
            if is_generating or not is_auto:
                socratic_input.hide()
                socratic_input.clear()
        
        if socratic_action_button:
            # Only hide if we are still waiting for the AI
            if is_generating or not is_auto:
                socratic_action_button.hide()

def on_show_question():
    """Hides the UI elements and starts background generation if auto-generate is on."""
    if socratic_dock:
        socratic_dock.hide()
        config = mw.addonManager.getConfig(__name__) or {}
        if config.get("auto_generate", False):
            on_generate_clicked()

def on_profile_loaded():
    """Setup UI once the user profile is loaded."""
    setup_ui()

# Hooks registration
 
# Hook to set up the UI elements on startup
gui_hooks.profile_did_open.append(on_profile_loaded)

# Hook to show our elements when the answer is revealed
gui_hooks.reviewer_did_show_answer.append(lambda card: on_show_answer())

# Hooks to hide our elements when moving away from the answer side
gui_hooks.reviewer_did_show_question.append(lambda card: on_show_question())
gui_hooks.reviewer_will_end.append(on_show_question)

# Register custom config UI
def open_config():
    from .config_ui import ConfigDialog
    dialog = ConfigDialog(__name__, mw)
    dialog.exec()

mw.addonManager.setConfigAction(__name__, open_config)
