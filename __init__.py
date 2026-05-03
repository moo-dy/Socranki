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
    """Renders text as HTML in the AnkiWebView, ensuring MathJax and Markdown support."""
    global chat_history_html
    config = mw.addonManager.getConfig(__name__) or {}
    font_size = config.get("ui_font_size", 14)
    
    # Protect MathJax tags from being mangled by the Markdown parser
    # Support all common styles: $$, $, \[, and \(
    content = re.sub(r'\$\$(.*?)\$\$', r'@@MATH_BLOCK_START@@\1@@MATH_BLOCK_END@@', content, flags=re.DOTALL)
    content = re.sub(r'\$([^$]+)\$', r'@@MATH_INLINE_START@@\1@@MATH_INLINE_END@@', content)
    content = content.replace("\\[", "@@MATH_BLOCK_START@@").replace("\\]", "@@MATH_BLOCK_END@@")
    content = content.replace("\\(", "@@MATH_INLINE_START@@").replace("\\)", "@@MATH_INLINE_END@@")
    
    try:
        import markdown
        formatted = markdown.markdown(content, extensions=['fenced_code', 'tables', 'sane_lists'])
    except ImportError:
        # Fallback if markdown is somehow missing
        formatted = content.replace("\n", "<br>")
        formatted = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", formatted)
        
    # Restore delimiters to standard LaTeX style for the browser-side MathJax engine
    formatted = formatted.replace("@@MATH_BLOCK_START@@", "\\[")
    formatted = formatted.replace("@@MATH_BLOCK_END@@", "\\]")
    formatted = formatted.replace("@@MATH_INLINE_START@@", "\\(")
    formatted = formatted.replace("@@MATH_INLINE_END@@", "\\)")
    
    new_block = f"<div style='margin-bottom: 10px;'>{formatted}</div>"
    
    if append:
        chat_history_html += "<hr style='border: 0; border-top: 1px solid #444; margin: 10px 0;'>" + new_block
    else:
        chat_history_html = new_block
        
    # Combine CSS and content without manually wrapping in <html> tags
    # so we can use stdHtml which injects Anki's MathJax scripts automatically.
    custom_css = f"""
    <style>
        body {{ 
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            font-size: {font_size}px; 
            line-height: 1.5;
            color: #d7d7d7;
            background-color: #2c2c2c;
            padding: 10px;
        }}
        b, strong {{ color: #007aff; font-weight: bold; }}
        hr {{ border-color: #444; }}
        pre {{ background-color: #1e1e1e; padding: 10px; border-radius: 5px; overflow-x: auto; }}
        code {{ background-color: #1e1e1e; padding: 2px 4px; border-radius: 3px; font-family: monospace; color: #ff9d00; }}
    </style>
    <script>
    MathJax = {{
      tex: {{
        inlineMath: [['$', '$'], ['\\\\(', '\\\\)']],
        displayMath: [['$$', '$$'], ['\\\\[', '\\\\]']]
      }},
      startup: {{
        typeset: false
      }}
    }};
    </script>
    <script id="MathJax-script" src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js"></script>
    <script>
      // Trigger typesetting slightly after load to ensure MathJax is ready
      setTimeout(function() {{
          if (typeof MathJax !== 'undefined' && MathJax.typesetPromise) {{
              MathJax.typesetPromise();
          }}
      }}, 50);
    </script>
    """
    
    full_html = custom_css + chat_history_html
    
    # We use setHtml to render our complete document including the MathJax CDN
    try:
        socratic_text_edit.setHtml(f"<html><head>{custom_css}</head><body>{chat_history_html}</body></html>")
    except Exception:
        pass

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
    elif backend_type == "anthropic":
        if not model_name:
            model_name = "claude-3-5-sonnet-20240620"
        url = "https://api.anthropic.com/v1/messages"
        payload = {
            "model": model_name,
            "max_tokens": 1024,
            "system": system_prompt,
            "messages": [
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 1.0
        }
        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01"
        }
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
            elif backend_type == "anthropic":
                try:
                    return result["content"][0]["text"]
                except (KeyError, IndexError):
                    return f"Error: Unexpected Anthropic response format: {json.dumps(result)}"
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

def get_contextual_knowledge_bg(note_id, card_id, deck_id, tags, note_text) -> str:
    """Fetches up to 5 related notes based on explicit NID links, tags, or deck."""
    seen_nids = set()
    seen_nids.add(note_id)
    
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
    explicit_nids = re.findall(r'nid[:\s]*(\d+)', note_text)
    
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

        except Exception:
            continue
            
    # 2. Search for Backlinks (notes pointing to THIS note)
    if len(context_strings) < 5:
        backlink_query = f"nid{note_id}"
        backlink_nids = mw.col.find_notes(backlink_query)
        for bnid in backlink_nids:
            if len(context_strings) >= 5:
                break
            if bnid not in seen_nids:
                try:
                    rel_note = mw.col.get_note(bnid)
                    add_note_to_context(rel_note, "Backlink")

                except Exception:
                    continue

    # 3. Search by tags or deck
    query_parts = []
    query_parts.append(f"-cid:{card_id}")
    
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
    """Determines Bloom's Taxonomy level based on card scheduling metadata and comprehension tags."""
    card_type = card.type
    ivl = card.ivl
    note = card.note()
    
    needs_comprehension = note.has_tag("needs_comprehension")
    
    if card_type in [0, 1, 3]:
        level_name = "Understanding"
        system_prompt = "Based on the concept, ask the user to explain it simply or summarize the core mechanism in their own words."
    elif card_type == 2 and ivl < 21:
        if needs_comprehension:
            level_name = "Understanding (Adapted)"
            system_prompt = "The user previously struggled with this concept. Break it down to basics. Ask the user to explain it simply or summarize the core mechanism in their own words."
        else:
            level_name = "Applying"
            system_prompt = "Invent a brief, novel real-world scenario. Ask the user how this concept applies to solve the scenario."
    else: # card_type == 2 and ivl >= 21
        if needs_comprehension:
            level_name = "Applying (Adapted)"
            system_prompt = "The user previously struggled with this concept. Let's practice application. Invent a brief, novel real-world scenario and ask how the concept applies to it."
        else:
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
    
    # Extract static variables for background processing
    note_id = note.id
    card_id = mw.reviewer.card.id
    deck_id = mw.reviewer.card.did
    tags = note.tags
    note_text = " ".join(note.values())
    
    output = f"--- Front ---\n{front_text}\n\n--- Back ---\n{back_text}"

    # Bloom's Taxonomy Logic
    bloom_level, bloom_prompt = get_bloom_prompt(mw.reviewer.card)

    config = mw.addonManager.getConfig(__name__) or {}
    mode = config.get("interaction_mode", "chit_chat")
    
    target_lang = config.get("target_language", "auto").strip()
    if not target_lang or target_lang.lower() == "auto":
        lang_instruction = "Respond in the same language as the flashcard content."
    else:
        lang_instruction = f"Respond in {target_lang}."
    
    angle = random.choice(SOCRATIC_ANGLES)
    variation_instruction = f"Be creative and approach the topic from this angle: {angle} Avoid repeating previous questions."
    
    personality = config.get("ai_personality", "Socranki")
    
    # Assembly
    strict_rules = (
        "STRICT RULES:\n"
        "1. NEVER introduce yourself or say hello.\n"
        "2. Keep your questions extremely concise (maximum 1-2 short sentences).\n"
        "3. Be highly specific and pertinent to the card content. Avoid vague, open-ended philosophical questions.\n"
        "4. DO NOT use conversational filler.\n"
        "5. EXACTLY ONE QUESTION: You must ask ONLY one single question. Do not provide multiple questions or options.\n"
        "6. MATH FORMATTING: If writing math or equations, you MUST use $ for inline math and $$ for block math. NEVER mix styles or use \(."
    )
    
    if mode == "one_liner":
        system_prompt = (
            f"You are {personality}, a Socratic tutor. {lang_instruction} {variation_instruction}\n"
            f"{strict_rules}\n\n"
            "You primarily ask follow-up questions to deepen understanding. You provide a single follow-up question and its ideal answer in the exact format:\n"
            "QUESTION: [your concise question here]\n"
            "ANSWER: [the ideal concise answer here]\n"
            f"{bloom_prompt}"
        )
    else:
        system_prompt = (
            f"You are {personality}, a Socratic tutor. {lang_instruction} {variation_instruction}\n"
            f"{strict_rules}\n\n"
            "You primarily ask one short, single follow-up question. Never give the answer immediately in the first turn.\n"
            f"{bloom_prompt}"
        )
    
    user_prompt = (
        f"Current Card Front: {front_text}\n"
        f"Current Card Back: {back_text}\n"
    )
    
    socratic_button.setEnabled(False)
    render_socratic_content(f"<i>Generating {bloom_level} question...</i>")
    if socratic_input: socratic_input.hide()
    if socratic_action_button: socratic_action_button.hide()
    
    is_generating = True
        
    def background_task():
        # Move heavy DB search off the main thread
        context_knowledge = get_contextual_knowledge_bg(note_id, card_id, deck_id, tags, note_text)
        
        final_user_prompt = user_prompt
        if context_knowledge:
            final_user_prompt += f"\nRelated Knowledge:\n{context_knowledge}"
            
        nonce = int(time.time() * 1000)
        final_user_prompt += f"\n\n[Variation Seed: {nonce}]"
        

        
        ai_response = fetch_ai_response(system_prompt, final_user_prompt, config)
        return ai_response, final_user_prompt
        
    def on_done(future):
        global is_generating, current_hidden_answer, current_ai_question, current_context
        socratic_button.setEnabled(True)
        try:
            result, final_prompt = future.result()
            current_context = final_prompt
            
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
            
        personality = config.get("ai_personality", "Socranki")
        tagging_enabled = config.get("enable_ai_tagging", False)
        
        tag_instruction = ""
        if tagging_enabled:
            tag_instruction = (
                "\n\nIMPORTANT INSTRUCTION: You MUST evaluate the user's comprehension. "
                "If their answer demonstrates solid understanding, append EXACTLY '[TAG: good_comprehension]' to the very end of your response. "
                "If their answer is wrong, confused, or they ask for help, append EXACTLY '[TAG: needs_comprehension]' to the very end of your response."
            )

        system_prompt = (
            f"You are {personality}, a Socratic tutor. The user has provided an answer to your previous Socratic question. {lang_instruction}\n"
            "STRICT RULES FOR EVALUATION:\n"
            "1. DO NOT applaud, praise, or sugarcoat. Avoid words like 'Great job!', 'Excellent!', or 'Spot on!'.\n"
            "2. Be direct, clinical, and extremely concise (1-2 sentences max).\n"
            "3. Evaluate the answer based on the flashcard context. Correct any misconceptions immediately.\n"
            "4. If the user asks for help, says they don't know, or seems genuinely stuck, provide a brief hint or the exact answer.\n"
            f"{tag_instruction}"
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
                
                # Parse AI Tags
                detected_tag = None
                if "[TAG: good_comprehension]" in result:
                    detected_tag = "good_comprehension"
                    result = result.replace("[TAG: good_comprehension]", "").strip()
                elif "[TAG: needs_comprehension]" in result:
                    detected_tag = "needs_comprehension"
                    result = result.replace("[TAG: needs_comprehension]", "").strip()
                
                # Apply tag if enabled
                tagging_enabled = config.get("enable_ai_tagging", False)
                if tagging_enabled and detected_tag and mw.reviewer.card:
                    note = mw.reviewer.card.note()
                    # Remove conflicting tags
                    if detected_tag == "good_comprehension" and note.has_tag("needs_comprehension"):
                        note.remove_tag("needs_comprehension")
                    elif detected_tag == "needs_comprehension" and note.has_tag("good_comprehension"):
                        note.remove_tag("good_comprehension")
                        
                    if not note.has_tag(detected_tag):
                        note.add_tag(detected_tag)
                        mw.col.update_note(note)
                        
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
    socratic_button.setStyleSheet("""
        QPushButton {
            background-color: #3a3a3a;
            color: #eee;
            border: 1px solid #555;
            border-radius: 6px;
            padding: 10px;
            font-size: 14px;
            font-weight: bold;
        }
        QPushButton:hover {
            background-color: #4a4a4a;
        }
    """)
    
    config = mw.addonManager.getConfig(__name__) or {}
    box_height = config.get("ui_box_height", 250)
    
    # Initialize web view
    socratic_text_edit = AnkiWebView()
    socratic_text_edit.setMinimumHeight(box_height)
    render_socratic_content("<i>Socratic question will appear here...</i>")
    
    socratic_input = QLineEdit()
    socratic_input.setPlaceholderText("Type your answer here...")
    socratic_input.returnPressed.connect(on_action_clicked)
    socratic_input.setStyleSheet("""
        QLineEdit {
            background-color: #333;
            color: #eee;
            border: 1px solid #555;
            border-radius: 6px;
            padding: 12px;
            font-size: 15px;
        }
        QLineEdit:focus {
            border: 1px solid #007aff;
        }
    """)
    socratic_input.hide()
    
    socratic_action_button = QPushButton("Action")
    socratic_action_button.clicked.connect(on_action_clicked)
    socratic_action_button.setStyleSheet("""
        QPushButton {
            background-color: #007aff;
            color: white;
            border: none;
            border-radius: 6px;
            padding: 12px;
            font-size: 15px;
            font-weight: bold;
        }
        QPushButton:hover {
            background-color: #006ce6;
        }
        QPushButton:disabled {
            background-color: #555;
            color: #888;
        }
    """)
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

def on_reviewer_will_end():
    """Cleanly hides the UI without triggering background generation."""
    if socratic_dock:
        socratic_dock.hide()

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
gui_hooks.reviewer_will_end.append(on_reviewer_will_end)

# Register custom config UI
def open_config():
    from .config_ui import ConfigDialog
    dialog = ConfigDialog(__name__, mw)
    dialog.exec()

mw.addonManager.setConfigAction(__name__, open_config)
