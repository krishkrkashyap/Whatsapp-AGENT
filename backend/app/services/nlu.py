"""NLU Service — BUG-6 fix: generate_answer uses _call_llm for all providers."""
import json
import re
import logging
from collections import OrderedDict
from app.config import settings

logger = logging.getLogger("nlu")

class NLUService:
    def __init__(self):
        self.provider = settings.llm_provider
        self.model = settings.llm_model
        self.api_key = settings.llm_api_key
        self._anthropic_client = None
        self._openai_client = None
        self._gemini_client = None

    def _get_anthropic(self):
        if self._anthropic_client:
            return self._anthropic_client
        import anthropic
        self._anthropic_client = anthropic.Anthropic(api_key=self.api_key)
        return self._anthropic_client

    def _get_openai(self):
        if self._openai_client:
            return self._openai_client
        import openai
        base_url = "https://api.groq.com/openai/v1" if self.provider == "groq" else None
        kwargs = {"api_key": self.api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._openai_client = openai.OpenAI(**kwargs)
        return self._openai_client

    def _get_gemini(self):
        if self._gemini_client:
            return self._gemini_client
        from google import genai
        self._gemini_client = genai.Client(api_key=self.api_key)
        return self._gemini_client

    def _call_llm(self, prompt: str, json_mode: bool = False) -> str:
        """Call configured LLM and return raw text response."""
        try:
            if self.provider in ("google", "gemini"):
                cl = self._get_gemini()
                model = self.model or "gemini-2.0-flash"
                if json_mode:
                    response = cl.models.generate_content(
                        model=model,
                        contents=prompt,
                        config={"response_mime_type": "application/json"},
                    )
                else:
                    response = cl.models.generate_content(model=model, contents=prompt)
                return response.text

            elif self.provider == "anthropic":
                cl = self._get_anthropic()
                model = self.model or "claude-3-5-haiku-latest"
                response = cl.messages.create(
                    model=model, max_tokens=1000,
                    messages=[{"role": "user", "content": prompt}],
                )
                return response.content[0].text

            else:  # openai / groq
                cl = self._get_openai()
                model = self.model or ("llama-3.3-70b-versatile" if self.provider == "groq" else "gpt-4o-mini")
                kwargs = {"model": model, "messages": [{"role": "user", "content": prompt}]}
                if json_mode:
                    kwargs["response_format"] = {"type": "json_object"}
                response = cl.chat.completions.create(**kwargs)
                return response.choices[0].message.content

        except Exception as e:
            logger.error(f"LLM call error ({self.provider}): {e}")
            raise

    _VALID_INTENTS = {"TASK_ASSIGN", "TASK_DONE", "TROUBLE_HELP", "FOLLOW_UP",
                       "STATUS_CHECK", "REGISTER", "HELP"}

    _FEWSHOT = """Examples (message -> intent):
"@Raj kal tak server theek karo" -> TASK_ASSIGN
"assign cleaning to Sapna every 2 hours" -> TASK_ASSIGN
"mera kaam ho gaya" -> TASK_DONE
"done 2" -> TASK_DONE
"samajh nahi aaya kaise karu" -> TROUBLE_HELP
"machine kaam nahi kar rahi" -> TROUBLE_HELP
"mere pending tasks batao" -> STATUS_CHECK
"kya karna hai aaj" -> STATUS_CHECK
"sabka status do" -> FOLLOW_UP
"mujhe add karo naam Raj" -> REGISTER
"aaj weather kya hai" -> HELP
"GST rate on bakery items?" -> HELP
"commands batao" -> HELP
"""

    def parse(self, text: str, employee_name: str = "", is_admin: bool = False,
              history: str = "") -> dict:
        """Parse incoming message. Returns intent, language, entities.

        Keyword fast-path handles unambiguous commands (assign with mention, done,
        register) instantly. Everything else goes to a few-shot LLM call whose
        result is accepted only when valid and confident; otherwise the keyword
        result stands.
        """
        keyword_result = self._keyword_parse(text, employee_name, is_admin)
        kw_intent = keyword_result.get("intent", "HELP")

        # High-precision keyword intents short-circuit the LLM (fast + reliable).
        if kw_intent in ("TASK_ASSIGN", "TASK_DONE", "REGISTER"):
            return keyword_result

        # Ambiguous (TROUBLE_HELP / STATUS_CHECK / FOLLOW_UP / HELP) — ask the LLM.
        if not self.api_key:
            return keyword_result

        hist_block = f"\nRecent conversation (for context):\n{history}\n" if history else ""
        system_prompt = f"""You are a task management assistant for an internal company WhatsApp bot.
Parse the employee message and extract intent and entities.

Available intents:
- TASK_ASSIGN: Admin assigning a task (real @mention or explicit "assign to"). Extract follow-up intervals ("every 30 min", "har 2 ghante").
- TASK_DONE: Employee confirming completion ("done", "ho gaya", "kar diya").
- TROUBLE_HELP: Employee stuck/needs help ("stuck", "error", "samajh nahi aaya", "kaise", "problem").
- FOLLOW_UP: Asking about task status ("follow up", "status", "sabka status").
- STATUS_CHECK: Employee asking their own tasks ("my tasks", "pending", "kya karna hai").
- REGISTER: New user wanting to register ("register", "add me", "mujhe add karo").
- HELP: Command list OR a general/world question (weather, prices, general chat).

CRITICAL: Only TASK_ASSIGN if a real @mention or "assign to" phrase is present. Domain names are not @mentions. General/world questions are HELP.
For TASK_ASSIGN with "every X min/hour" / "har X minute/ghanta": follow_up_type="periodic", interval_hours=decimal hours (30 min=0.5, 2 hours=2.0).

{self._FEWSHOT}{hist_block}
Respond in JSON ONLY:
- "intent": one of the intents above
- "language": "hindi"|"english"|"hinglish"|"gujarati"|"gujlish"
- "confidence": 0.0 to 1.0 (how sure you are of the intent)
- "entities": {{"target_name": str|null, "task_description": str|null, "priority": "high"|"medium"|"low"|null, "due_date": str|null, "follow_up_type": "periodic"|null, "interval_hours": number|null, "register_name": str|null}}

Message from {employee_name} (is_admin={is_admin}): {text}"""

        try:
            raw = self._call_llm(system_prompt, json_mode=True)
            parsed = json.loads(raw)
            llm_intent = parsed.get("intent", "HELP")
            # Missing confidence -> treat as 0 (reject) so a keyless, possibly
            # low-quality intent doesn't sail through the gate.
            confidence = parsed.get("confidence", 0.0)
            try:
                confidence = float(confidence)
            except (TypeError, ValueError):
                confidence = 0.0
            if llm_intent not in self._VALID_INTENTS or confidence < 0.55:
                logger.info("LLM intent rejected (intent=%s conf=%s) -> keyword", llm_intent, confidence)
                return keyword_result
            return parsed
        except Exception as e:
            logger.warning(f"NLU API error: {e}")
            return keyword_result

    def classify_task_completion(self, message: str, pending: list) -> dict:
        """Context-aware: decide if `message` reports/completes ONE of the
        employee's pending tasks. `pending` = [{"id","title"}]. Many tasks are
        'report' tasks completed by replying with the requested value (a count,
        status, short answer) instead of typing 'done'.
        Returns {"task_id": <id>|None, "answer": <reported value/summary>}."""
        if not self.api_key or not pending:
            return {"task_id": None, "answer": ""}
        listing = "\n".join(f'{i+1}. id={t["id"]} | {t["title"]}' for i, t in enumerate(pending))
        prompt = (
            "You classify a WhatsApp message from a factory/kitchen employee who has open tasks.\n"
            "Many tasks are REPORT tasks: the worker completes them by replying with the requested "
            "info (a number, count, status or short answer) INSTEAD of typing \"done\".\n\n"
            f'Message: "{message}"\n\n'
            f"The employee's pending tasks:\n{listing}\n\n"
            "If this message is REPORTING the answer/data for, or otherwise completing, exactly ONE of "
            "these tasks, return that task's id.\n"
            "Return null if: it is a question; a greeting/small talk; a problem/complaint/blocker; or it "
            "says the task is NOT done, incomplete, pending, delayed, or still in progress. Only return an "
            "id when the task is genuinely COMPLETE with the answer provided.\n"
            'Respond JSON only: {"task_id": "<id>" or null, "answer": "<reported value or short summary>"}'
        )
        try:
            raw = self._call_llm(prompt, json_mode=True)
            data = json.loads(raw)
            tid = data.get("task_id")
            if tid and any(str(t["id"]) == str(tid) for t in pending):
                return {"task_id": str(tid), "answer": (data.get("answer") or "").strip()}
        except Exception as e:
            logger.warning("task-completion classify failed: %s", e)
        return {"task_id": None, "answer": ""}

    @staticmethod
    def _extract_interval(text_lower: str) -> tuple:
        """Extract follow-up interval from text like 'every 30 min' / 'every 2 hours'.
        Returns (follow_up_type, interval_hours).
        """
        m = re.search(r'every\s+(\d+)\s*(min|mins|minute|minutes|hour|hours|hr|hrs|h|m)\b', text_lower)
        if not m:
            # Hindi/Hinglish: "har 30 minute" / "har 2 ghante"
            m = re.search(r'har\s+(\d+)\s*(min|mins|minute|minutes|ghante|ghanta|hour|hours|hr|hrs|h|m)\b', text_lower)
        if not m:
            # Gujarati/Gujlish: "dar 30 min"
            m = re.search(r'dar\s+(\d+)\s*(min|mins|minute|minutes|m)\b', text_lower)
        if not m:
            # "follow up every X min", "reminder every X hour"
            m = re.search(r'(?:follow|reminder|notify|check)\s+(?:up|me|every|each|har|dar)\s+(\d+)\s*(min|mins|minute|minutes|hour|hours|hr|hrs|h|m)\b', text_lower)
        if not m:
            # X minutes/hours followup
            m = re.search(r'(\d+)\s*(min|mins|minute|minutes|hour|hours|hr|hrs|h|m)\s+(?:follow|reminder|pachhi|bad)\b', text_lower)

        if m:
            num = int(m.group(1))
            unit = m.group(2)[0]  # 'm' or 'h'
            if unit == 'm' or unit == 'M':
                interval_hours = num / 60.0
            else:
                interval_hours = float(num)
            return ("periodic", interval_hours)
        return (None, None)

    def _keyword_parse(self, text: str, employee_name: str, is_admin: bool) -> dict:
        text_lower = text.lower()
        mention = re.search(r"@(\w+)", text)

        # also detect "assign to <name>" / "task to <name>" / "<name> ko" without @
        assign_to = re.search(r"(?:assign|task|delegate)\s+(?:to|kar|do|de)\s+(\w+)", text_lower)
        name_from_assign = mention.group(1) if mention else (assign_to.group(1) if assign_to else None)

        # BUG-C8 fix: Use word-boundary matching to prevent false positives
        # (e.g. "complete" in "completely" or "done" in "abandoned").
        # Done detection is delegated to helpers.is_done_command, which covers all
        # Hindi/Hinglish/Gujarati/English variants incl. 'done N'/'hogya1' forms.
        from app.utils.helpers import is_done_command
        help_words = ["stuck", "error", "samajh nahi aaya", "mushkil", "kaise", "problem", "issue", "nahi ho raha", "samasya", "madaad", "help", "ખબર નથી"]
        status_words = ["my tasks", "my task", "pending", "kya karna", "kaunsa task", "mera task", "mara task", "shu karvanu"]
        follow_words = ["follow up", "followup", "follow-up", "check status", "status check", "kaun late", "ko late", "kon baki"]
        register_words = ["register", "sign up", "signup", "add me", "mujhe add karo", "mujhe register", "mari registration"]

        if self._word_match(register_words, text):
            return {"intent": "REGISTER", "language": self._detect_language(text), "entities": {"register_name": text}, "response_text": "Registration request received"}

        if name_from_assign and is_admin:
            follow_up_type, interval_hours = self._extract_interval(text_lower)
            priority = "high" if self._word_match(["urgent", "jaldi", "high"], text) else "medium"
            return {
                "intent": "TASK_ASSIGN",
                "language": self._detect_language(text),
                "entities": {
                    "target_name": name_from_assign,
                    "task_description": text,
                    "priority": priority,
                    "due_date": None,
                    "follow_up_type": follow_up_type,
                    "interval_hours": interval_hours
                },
                "response_text": f"Task assigned to {name_from_assign}"
            }

        if is_done_command(text):
            return {"intent": "TASK_DONE", "language": self._detect_language(text), "entities": {}, "response_text": "Task marked as done!"}
        if self._word_match(help_words, text):
            return {"intent": "TROUBLE_HELP", "language": self._detect_language(text), "entities": {"task_description": text}, "response_text": "Searching for solution..."}
        if self._word_match(follow_words, text):
            return {"intent": "FOLLOW_UP", "language": self._detect_language(text), "entities": {}, "response_text": "Checking task status..."}
        if self._word_match(status_words, text):
            return {"intent": "STATUS_CHECK", "language": self._detect_language(text), "entities": {}, "response_text": "Here are your pending tasks..."}
        if self._word_match(["help", "commands", "kya kar"], text):
            return {"intent": "HELP", "language": self._detect_language(text), "entities": {}, "response_text": "Here are the commands..."}
        return {"intent": "HELP", "language": self._detect_language(text), "entities": {}, "response_text": ""}

    @staticmethod
    def _word_match(words: list, text: str) -> bool:
        """Match whole words only (not substrings). Uses word boundaries for all words."""
        text_lower = text.lower()
        for w in words:
            # CQ-6 fix: Use module-level re (already imported), not local import
            # BUG-C8 fix: Use word boundary for ALL words, not just short ones,
            # to prevent "complete" matching "completely"
            if re.search(r'\b' + re.escape(w) + r'\b', text_lower):
                return True
        return False

    def _detect_language(self, text: str) -> str:
        text_lower = text.lower()
        has_ascii = any(c.isascii() and c.isalpha() for c in text)
        hindi_words = ["hai", "nahi", "kya", "karna", "ho", "gaya", "kar", "mujhe", "aaya", "samajh", "mujhse", "bhai", "boss", "kaun", "sab", "mere", "paas"]
        gujarati_chars = set("કખગચછજટઠડણતથદધનપફબભમયરલવશષસહળ")

        # Pure Gujarati script (no ASCII letters) → gujarati
        if any(c in text for c in gujarati_chars) and not has_ascii:
            return "gujarati"

        # Gujarati script WITH ASCII letters → gujlish (Engli-Gujarati mix)
        if any(c in text for c in gujarati_chars) and has_ascii:
            return "gujlish"

        # Gujarati words in Latin script (no Gujarati Unicode) → gujlish
        # BUG-C10 fix: Removed "have" — it's a common English word causing false positives.
        # Also removed duplicate "chhu" and "chhe".
        gujlish_signals = ["che", "nathi", "karva", "chhu", "chhe", "aapde", "tamne", "mane", "pachi", "kyare", "sau", "koi", "pan", "karo", "kare", "joyo", "jovo", "joje", "shu", "kem", "chho", "thayu", "karvu"]
        if self._word_match(gujlish_signals, text):
            if has_ascii:
                return "gujlish"
            return "gujarati"

        if self._word_match(hindi_words, text):
            if has_ascii:
                return "hinglish"
            return "hindi"
        return "english"

    @staticmethod
    def _is_safe_url(url: str) -> bool:
        """Block SSRF: reject private/internal IPs."""
        import urllib.parse
        host = urllib.parse.urlparse(url).hostname or ""
        # Block bare hostnames that aren't full domain names (e.g. http://localhost)
        if host and "." not in host and host != "localhost":
            return False
        # Block localhost
        if host in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
            return False
        # Block private IP ranges
        import ipaddress
        try:
            ip = ipaddress.ip_address(host)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
                return False
        except ValueError:
            pass  # hostname (not IP) — allow, DNS will resolve
        # Block common internal hostnames
        blocked = ["169.254.169.254", "metadata", "metadata.google.internal"]
        if any(b in host for b in blocked):
            return False
        return True

    def webfetch(self, url: str) -> str:
        """Fetch web content and summarize with LLM. SSRF-safe.
        BUG-C9 fix: Uses httpx (non-blocking) instead of urllib.request (blocking).
        """
        if not self._is_safe_url(url):
            return "❌ Internal URLs are not allowed for security reasons."
        try:
            import httpx
            resp = httpx.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15, follow_redirects=True)
            resp.raise_for_status()
            html = resp.text
            # strip tags for clean text
            text = re.sub(r"<[^>]+>", " ", html)
            text = re.sub(r"\s+", " ", text).strip()[:4000]
            if not self.api_key:
                return text[:1000]

            prompt = f"Summarize the following web page content concisely:\n\n{text}"
            return self._call_llm(prompt)
        except Exception as e:
            return f"❌ Web fetch error: {e}"

    def _lang_label(self, language: str) -> str:
        """Map internal language codes to LLM-friendly descriptions."""
        return {
            "gujlish": "Gujlish (Gujarati-English mix, like 'tamne khabar che?')",
            "gujarati": "Gujarati",
            "hinglish": "Hinglish (Hindi-English mix)",
            "hindi": "Hindi",
            "english": "English",
        }.get(language, "English")

    def ask(self, question: str, context: str = "", language: str = "english") -> str:
        """Ask the LLM a question with optional context."""
        if not self.api_key:
            if context:
                return f"Based on available info: {context[:300]}"
            return "AI not configured. Set LLM_API_KEY for smart responses."

        system = f"You are a helpful WhatsApp assistant. Answer in {self._lang_label(language)} only. Be concise (max 200 words)."
        if context:
            system += f"\n\nUse this context to answer:\n{context}"
        system += f"\n\nQuestion: {question}"
        return self._call_llm(system)

    def verify_task_assign(self, original_text: str, parsed_entities: dict) -> dict:
        """Verify parsed task assignment with LLM. Returns corrected entities dict.
        Only modifies target_name, task_description, priority, follow_up_type, interval_hours.
        Falls back to input entities if no API key or LLM fails.
        """
        if not self.api_key:
            return parsed_entities

        prompt = (
            f"Original message from admin: \"{original_text}\"\n\n"
            f"Parser extracted these entities:\n"
            f"- target_name: {parsed_entities.get('target_name')}\n"
            f"- task_description: {parsed_entities.get('task_description', '')[:200]}\n"
            f"- priority: {parsed_entities.get('priority')}\n"
            f"- follow_up_type: {parsed_entities.get('follow_up_type')}\n"
            f"- interval_hours: {parsed_entities.get('interval_hours')}\n\n"
            f"TASK: Verify and correct if needed.\n"
            f"1. Is the target_name correct (the person being assigned)? If unclear, keep as-is.\n"
            f"2. Extract ONLY the actual task description (remove @mentions, priority words, deadlines, follow-up instructions).\n"
            f"3. Is the priority correct? (high = urgent/jaldi/important/priority, medium = default)\n"
            f"4. Does the message mention a follow-up interval? (every X min/hour, har X minute/ghanta, reminder).\n"
            f"   If yes: follow_up_type = \"periodic\", interval_hours = decimal hours (30 min = 0.5, 1 hour = 1.0, 45 min = 0.75)\n"
            f"   If no: follow_up_type = null, interval_hours = null\n\n"
            f"Respond in JSON ONLY with these keys:\n"
            f"{{\n"
            f"  \"target_name\": \"string or null\",\n"
            f"  \"task_description\": \"cleaned task description only\",\n"
            f"  \"priority\": \"high/medium/low\",\n"
            f"  \"follow_up_type\": \"periodic\" or null,\n"
            f"  \"interval_hours\": number or null\n"
            f"}}"
        )
        try:
            raw = self._call_llm(prompt, json_mode=True)
            corrected = json.loads(raw)
            # Merge corrections into original entities
            result = dict(parsed_entities)
            for key in ("target_name", "task_description", "priority", "follow_up_type", "interval_hours"):
                if key in corrected and corrected[key] is not None:
                    result[key] = corrected[key]
            return result
        except Exception as e:
            logger.warning("Task verification LLM error: %s — using parsed entities as-is", e)
            return parsed_entities

    # BUG-C5 fix: LRU cache with max 500 entries (was unbounded dict)
    _translation_cache: OrderedDict = OrderedDict()
    _TRANSLATION_CACHE_MAX = 500

    def translate(self, text: str, target_language: str) -> str:
        """Translate a hardcoded template string to target language.
        Cached per (text, lang) pair so repeated strings are instant.
        Falls back to original text if no API key or if translation fails.
        """
        if target_language == "english" or not target_language:
            return text
        key = (text, target_language)
        cached = self._translation_cache.get(key)
        if cached:
            # Move to end (most recently used)
            self._translation_cache.move_to_end(key)
            return cached
        if not self.api_key:
            return text
        lang_label = self._lang_label(target_language)
        prompt = (
            f"Translate the following text to {lang_label} only. "
            f"Keep all emojis, formatting (*bold*, bullet points), and line breaks exactly as-is. "
            f"Output ONLY the translation, nothing else.\n\n{text}"
        )
        try:
            result = self._call_llm(prompt).strip()
            # Remove any surrounding quotes the LLM might add
            result = result.strip('"\'')
            self._translation_cache[key] = result
            # Evict oldest entries if cache exceeds max size
            while len(self._translation_cache) > self._TRANSLATION_CACHE_MAX:
                self._translation_cache.popitem(last=False)
            return result
        except Exception as e:
            logger.warning("Translation failed for '%s' -> %s: %s", text[:30], target_language, e)
            return text

    def generate_answer(self, question: str, context: str, language: str) -> str:
        """BUG-6 FIX: Generate answer using unified _call_llm (supports all providers)."""
        if not self.api_key:
            return f"Based on our documentation: {context[:300]}"

        lang_label = self._lang_label(language)
        prompt = (
            f"Based on the context below, answer the question in {lang_label} only.\n\n"
            f"Context: {context}\n\nQuestion: {question}\n\n"
            f"Answer concisely and helpfully in {lang_label}."
        )
        try:
            return self._call_llm(prompt)
        except Exception as e:
            logger.error(f"LLM answer error: {e}")
            return context[:300]

nlu_service = NLUService()
