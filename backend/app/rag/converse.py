"""Greetings and off-topic questions (D84): how to recognise them and how to answer them.

The agent (app/rag/agent.py) sends a question here when it is a greeting, or when it names no
drug and no medical word, does not point back at the confirmed pills, and the documents hold
nothing close to it. The answer then comes from the LLM's general knowledge, without sources,
and is marked as such.
"""

# ruff: noqa: RUF001  (the Russian prompt and patterns use Cyrillic letters on purpose)

from __future__ import annotations

import re

CYRILLIC = re.compile(r"[\u0400-\u04ff]")

# Words that make a question medical (folded text), even without a known drug name: such a
# question always goes to the documents and the cited answer, never to a general answer.
MEDICAL = re.compile(
    r"\b(?:medic\w*|drugs?|pills?|comprim\w*|tablets?|gelules?|capsules?|pharmac\w*|"
    r"ordonnances?|prescri\w*|traitements?|treat\w*|therap\w*|interact\w*|"
    r"side[- ]effects?|effets? (?:secondaires?|indesirables?)|adverse|symptom\w*|"
    r"maladies?|diseases?|sante|health\w*|douleurs?|pains?|fievre|fever|allerg\w*|"
    r"infections?|antibio\w*|vaccin\w*|grossesse|enceinte|pregnan\w*|allait\w*|"
    r"breast[- ]?feed\w*|diabet\w*|tension|hypertens\w*|cholesterol|cancers?|asthm\w*|"
    r"depress\w*|anxi\w*|insomni\w*|migraines?|headaches?|doctors?|medecins?|"
    r"hospital\w*|hopital\w*|toxi\w*|overdose|surdose|contre[- ]?indi\w*|"
    r"contraindicat\w*|posologie|alcool|alcohol)\b"
)
# With confirmed pills, words that point back at them or at taking them (folded text): "and
# together?", "can I take them with coffee?", "pourquoi ?", "c'est grave ?". Such a question
# stays with the documents; one without them ("trump") gets the off-topic check like any other.
# On the real index these follow-ups score 0.47-0.62, off-topic words at most 0.43.
FOLLOW_UP = re.compile(
    r"\b(?:them|they|their|these|those|it|its|both|together|same time|compatible|"
    r"combin\w*|mix\w*|take|taking|with|avoid|watch|careful|risk\w*|danger\w*|serious|"
    r"why|explain\w*|more|ensemble|les|eux|ils|elles|ces|cela|leurs?|meme temps|avec|"
    r"prendre|melang\w*|eviter|surveill\w*|risques?|grave|pourquoi|expliqu\w*|plus)\b"
)
# Greetings, thanks and questions about Tujya itself (folded text, a few words at most).
SMALL_TALK = re.compile(
    r"^\W*(?:hi+|hello|hey|yo|hiya|salut|slt|bonjour|bonsoir|coucou|"
    r"good (?:morning|afternoon|evening)|thanks?(?: you)?|thx|merci(?: beaucoup)?|"
    r"ok(?:ay)?|d'accord|bye|goodbye|au revoir|a bientot|how are you|ca va|"
    r"comment (?:ca va|vas[- ]tu|allez[- ]vous)|who are you|what are you|qui es[- ]tu|"
    r"qui etes[- ]vous|what can you do|que (?:peux|sais)[- ]tu faire|help|aide(?:[- ]moi)?|"
    r"привет|здравствуите|добрыи (?:день|вечер)|спасибо|пока|кто ты)"
    r"(?:\W+\w+){0,3}\W*$"
)
# A Russian quantity of medicine, for the general answers (the DOSE rule reads French and
# English). Folded text: "й" loses its breve.
RU_DOSE = re.compile(r"\d+(?:[.,]\d+)?\s*(?:мг|мкг|мл|г\b|таблет\w*|капсул\w*)|\bдоз\w*")

CONVERSE_PROMPT = {
    "en": """You are Tujya, a friendly assistant. Your speciality is medicine information: you
identify pills from a photo, check drug interactions in DDInter and answer questions about
medicines from drug labels and PubMed, with citations. Answer in English.
- If the user greets you, thanks you, or asks who you are or what you can do, reply warmly in
  one or two sentences and say what you can help with.
- Otherwise the question is not about medicines: answer it briefly and factually from your
  general knowledge, in 2 to 4 short sentences, in a neutral, encyclopedic tone. If you are not
  sure of a fact, say so instead of guessing. A message that is only a name or a few words
  ("trump", "Eiffel Tower") means "who or what is it?": answer that.
- If the question is in fact about health, symptoms, a disease or a medicine, do not answer it
  from memory: say that you answer health questions only from your medical sources, and ask the
  user to name the medicine.
- Politely refuse anything hateful, violent or illegal.
- Never give a dose, a dosage or how often to take a medicine. No heading, no list.""",
    "fr": """Tu es Tujya, un assistant sympathique. Ta spécialité est l'information sur les
médicaments : tu identifies des comprimés sur une photo, tu vérifies les interactions dans
DDInter et tu réponds aux questions sur les médicaments à partir des notices et de PubMed, avec
des citations. Réponds en français.
- Si l'utilisateur te salue, te remercie, ou demande qui tu es ou ce que tu sais faire, réponds
  chaleureusement en une ou deux phrases et dis en quoi tu peux l'aider.
- Sinon, la question ne porte pas sur les médicaments : réponds brièvement et factuellement avec
  tes connaissances générales, en 2 à 4 phrases courtes, sur un ton neutre et encyclopédique. Si
  tu n'es pas sûr d'un fait, dis-le au lieu de deviner. Un message qui n'est qu'un nom ou
  quelques mots (« trump », « tour Eiffel ») veut dire « qui ou qu'est-ce que c'est ? » :
  réponds à cela.
- Si la question porte en fait sur la santé, des symptômes, une maladie ou un médicament, n'y
  réponds pas de mémoire : dis que tu ne réponds aux questions de santé qu'à partir de tes
  sources médicales, et demande le nom du médicament.
- Refuse poliment tout contenu haineux, violent ou illégal.
- Ne donne JAMAIS de dose, de posologie ni de fréquence de prise. Pas de titre, pas de liste.""",
    "ru": """Ты Tujya, дружелюбный помощник. Твоя специализация — информация о лекарствах:
ты распознаёшь таблетки по фото, проверяешь взаимодействия в DDInter и отвечаешь на вопросы о
лекарствах по инструкциям и PubMed, со ссылками на источники. Отвечай по-русски.
- Если пользователь здоровается, благодарит или спрашивает, кто ты и что умеешь, ответь
  тепло в одном-двух предложениях и скажи, чем можешь помочь.
- Иначе вопрос не о лекарствах: ответь кратко и по фактам из общих знаний, в 2–4 коротких
  предложениях, нейтрально, как энциклопедия. Если не уверен в факте, так и скажи.
  Сообщение из одного имени или пары слов («трамп», «Эйфелева башня») значит «кто или
  что это?»: ответь на это.
- Если вопрос на самом деле о здоровье, симптомах, болезни или лекарстве, не отвечай по
  памяти: скажи, что на вопросы о здоровье отвечаешь только по медицинским источникам, и
  попроси назвать лекарство.
- Вежливо откажись от всего ненавистнического, жестокого или незаконного.
- НИКОГДА не называй дозу, дозировку или частоту приёма. Без заголовков и списков.""",
}
# When the safety rules remove every sentence of a general answer.
CONVERSE_FALLBACK = {
    "en": "I can only help with this through my medical sources: please name the medicine.",
    "fr": "Je ne peux aider ici qu'avec mes sources médicales : indiquez le nom du médicament.",
    "ru": "Здесь я могу помочь только по медицинским источникам: назовите лекарство.",
}
