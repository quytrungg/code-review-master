# Google developer documentation style — condensed rules

Source: https://developers.google.com/style — condensed from the full guide (voice/tone, grammar, punctuation, formatting, lists, procedures, numbers, dates, units, code samples, UI text, links, notices, inclusive language, word list). Apply these rules to every review comment and synthesized output. The guide itself says these are guidelines, not laws: deviate only when clarity for the reader improves.

## Voice and tone

- Write conversationally, friendly, and respectfully. Not slang, not overly formal, not cutesy, not wacky, not pushy.
- Sound like a knowledgeable friend who understands what the developer wants to do. Be human, but information comes first.
- No exclamation marks. No humor. No pop-culture references. No buzzwords or jargon.
- Do not start every sentence with the same phrase (such as "You can" or "To do").
- No "let's" phrasing. No internet slang or abbreviations ("tl;dr", "ymmv", "RTFM").
- No "please" in instructions. No placeholder phrases: "please note", "at this time".
- Never write "simply", "It's that simple", "It's easy", or "quickly" about a task or fix.

## Person and voice

- Second person: "you", never "we", "let's", or "the user" for the reader.
- Avoid first person (I, we, us, our) except when quoting or stating an author's own position.
- Active voice. Make the doer the subject: "The serializer drops the nil branch", not "the nil branch is dropped by the serializer". Passive is acceptable only to emphasize the object, de-emphasize the actor, or when the actor is irrelevant.
- Present tense for general behavior ("The server sends an acknowledgment", not "will send"). Future tense only for a genuinely future, delayed action. No hypothetical "would".
- In API reference comments, third-person present tense: "tasks.insert: Creates a new task", not "Create a new task".
- No anthropomorphism. Do not attribute human qualities to software or hardware: "The PC detects a new device", not "sees"; "The method returns", not "wants" or "knows".
- Avoid directional language ("above", "below", "left panel"). Use "earlier", "preceding", "following".

## Sentence structure

- Put conditions before instructions: "To delete the entire document, click Delete", not "Click Delete if you want to delete the entire document".
- Standard subject + verb + object order. Keep subject and verb close together.
- Sentences short, ideally under 26 words. Important information in the first sentence of the paragraph.
- One topic per paragraph. Do not force line breaks inside sentences.
- Place "only" immediately before what it limits: "Request only one token", not "Only request one token".
- No double negatives, no exceptions to exceptions. Prefer positive constructions: "You can continue without a path", not "A missing path won't prevent you from continuing".
- Keep helper words ("then", "that", "of") and relative pronouns ("that", "which") where dropping them creates ambiguity. Prefer "the link that you want to open" over "the link you want to open".
- Use simple words: "start" not "commence", "so" not "consequently", "use" not "utilize" or "leverage", "about" not "approximately".
- Avoid phrasal verbs where a simpler verb exists ("make use of" → "use"). Accepted exceptions: "set up", "log in", "sign in".
- Match the spelling of the codebase and the repository. Employment Hero code and identifiers are British English (`organisation`, `behaviour`, `serialise`), so a comment about `current_organisation` keeps that spelling; a repository that spells the same word differently decides for itself.

## Modality (must, should, can)

- "Must" for a strict requirement. "Should" only for a genuine recommendation. "Can" for permission or ability.
- Avoid vague prescriptive "should" where the code requires the behavior. State what the code does, then what it must do.

## Claims

- No excessive claims: no unverifiable performance, cost, or security claims. No superlatives ("best", "fastest", "simplest"). No "never" or "always" unless literally true.
- "Ensure" and "guarantee" only when truly guaranteed. Security claims: "is designed for security" or "helps prevent", never "prevents" or "is secure".
- Performance claims need a cited source. State facts that stay true over the document's life.

## Inclusive language

- No ableist language: crazy, insane, cripple, dumb, blind to, sanity check (use "final check"), dummy variable (use "placeholder variable").
- No unnecessarily gendered language: "person-hours" not "man-hours", "humanity" not "mankind". No gendered pronouns unless the person's gender is known.
- No graphic or violent metaphors: kill, hang ("stop responding"). Use precise terms. Exceptions only where the term is a technical necessity (for example, the `SIGKILL` signal).
- Prefer "allowlist"/"denylist" over "whitelist"/"blacklist"; "primary/replica" over "master/slave". No "first-class citizen" — use "fully supported" or state the actual capability.
- If a non-inclusive term is embedded in code, refer to it in code font once (for example, the `whitelist` command), then use the preferred term.
- Do not describe people without disabilities as "normal".

## Global audience

- Avoid idioms, slang, colloquialisms, humor, and culturally specific references (holidays, sports, seasons). Say "quarter 3", not "Q3 summer".
- Define abbreviations on first use: spell out first, abbreviation in parentheses, italics for the spelled-out term when discussing it. Do not nest abbreviations ("IoT (internet of things)", not "IoT (internet of things) (a type of network)").
- Never use "i.e.", "e.g.", or "etc." in prose. Use "that is", "for example", "and so on".
- Clarify ambiguous pronouns by repeating the noun: "If you type text in the field, the text doesn't change", not "it doesn't change".
- Use consistent terminology: one term for one concept, same capitalization everywhere. Repeat a word rather than cycling synonyms.
- Do not use the same word as both noun and verb in close proximity.

## Formatting

- Sentence case for all headings, titles, navigation, list items, table elements, and captions. No period at the end of a heading.
- Bold only for UI elements and run-in headings. Do not bold feature or product names, and do not use `__` in Markdown.
- Italics only for words-as-words and term definitions. Use sparingly.
- Code font for code, filenames, class and method names, HTTP status codes and verbs, IP addresses, port numbers, query parameters, environment variables, language keywords, placeholders, command output, and text the user types. No angle brackets around element names (`script`, not `<script>`).
- Placeholders in all caps: `PROJECT_ID`, `SUBNETWORK_NAME`.
- Serial commas: "a, b, and c". One space after a period, not two.
- Straight quotes, not curly quotes. Periods and commas inside quotation marks (US style).
- No `&` as a substitute for "and" in headings, text, or navigation. OK in code and UI labels.

## Punctuation

- Em dash for emphasis or an aside; do not substitute an en dash or hyphen. Use dashes sparingly, and never as a lazy "Example -" label.
- Hyphen for number ranges ("8-20 files", "5-10 minutes") with no spaces; or "from 8 to 20". Never mix: not "from 8-20 files".
- Colon after an independent clause; lowercase after a colon unless a proper noun, heading, quotation, or vertical list follows.
- Avoid semicolons where separate sentences work. Avoid ellipses in prose entirely.
- Parentheses for asides, not for optional plurals ("6 instances", not "6 instance(s)").
- No slashes for alternatives: "and", "or", or "both", not "and/or", "developed/hosted", "5/6 times". No slash dates. "per" over "/": "requests per day", not "requests/day". No "w/", "c/o" style abbreviations.

## Numbers, dates, times, units

- Spell out zero through nine; numerals for 10 and greater. Numerals always for: version numbers, technical quantities (memory, disk, queries, limits), percentages, currency, dimensions, step references.
- Spell out ordinals: "first", "second", not "1st", "2nd".
- No comma in a four-digit year. Dates: "January 19, 2017"; numeric only, ISO 8601 (`2017-04-15`). No seasons for timeframes.
- Times: 12-hour clock, "3 PM" for round hours, "3:45 PM" otherwise, one space before AM/PM. Hyphen in time ranges: "5-10 minutes". Avoid time zones unless necessary.
- One space between a number and its unit, ideally nonbreaking; no space before "%" or "$" ("65%", "$10"). No space in "180°". Do not pluralize abbreviated units: "64 GB", not "64 GBs".
- Use "to" between ranged temperatures: "-40 °C to 85 °C", not "-40-85 °C".
- Distinguish decimal from binary units: kB/MB/GB (1000-based) vs KiB/MiB/GiB (1024-based). Do not write GB when you mean GiB.
- Hyphenate compound modifiers before a noun ("a five-minute wait", "a well-designed app", "a 64-bit system"); no hyphen in predicate position ("the app is well designed"). No hyphen after -ly adverbs ("publicly available"). No hyphens in established closed compounds: webpage, hostname, tradeoff, workaround.

## Lists and procedures

- Numbered lists for sequences, bulleted lists otherwise. Never a list of one item.
- Introduce every list with a complete sentence ending in a colon.
- List items parallel in structure, sentence case, consistent end punctuation (periods for full sentences).
- Procedures: numbered steps, one action per step. A single-step procedure is one sentence, not a numbered list.
- "Optional:" prefix for optional steps. Use "do the following:" to introduce multi-part steps.
- Command syntax: square brackets for optional arguments, curly braces with `|` for choose-one, `...` for repeatable values. Introduce output with "The output is similar to the following:".
- In code samples, explain omissions with a comment rather than a bare ellipsis.

## Headings

- Sentence case, descriptive, unique. Task headings start with a bare infinitive ("Configure notebook settings"); concept headings are noun phrases ("ML model monitoring overview").
- Do not skip heading levels. Do not end headings with punctuation.

## Links and cross-references

- Descriptive link text that makes sense out of context. Never "click here" or a bare URL.
- Introduce with "see": "For more information about indexes, see Managing indexes." Use "about", not "on".
- Be selective: each link adds cognitive load. Do not duplicate the same link needlessly. Provide short context on the page instead of linking for two sentences' worth of information.

## Notices

- Use sparingly. Note (useful aside), Caution (proceed carefully), Warning (irreversible or risk of loss).
- Never use notices for prerequisites, expected results, information in flow with the text, or cross-references. Do not stack notices.

## UI text

- Bold UI elements; do not use them as verbs or nouns: "To save the settings, click Save", not "Save the settings."
- Use correct nouns: page, dialog, pane, window, menu. Not "pop-up window", not "drop-down", no slang ("hamburger icon", "zippy" → "expander arrow").
- Render UI labels in sentence case even when the label is all caps. Do not add "button" after a label.
- Keyboard shortcuts: "Control+C", not "Ctrl+C"; "Esc" for the Escape key; "select" or "clear" a checkbox; "selected"/"not selected" for state.
- Prepositions: "in" for dialogs, fields, lists, menus, panes, windows; "on" for pages, tabs, toolbars.

## Terminology and word choice

- No product names as verbs. Full product names; no "the" before a product name, but "the" before tool and API names ("the gcloud CLI").
- Do not form possessives of code items ("the `wordCount` method's return value" → "the value returned by the `wordCount` method").
- No `'s` plurals on abbreviations: "APIs", not "API's". Pluralize the noun, not the abbreviation in units: "virtual machines (VMs)", "64 GB".
- No acronyms as verbs: "Use SSH to log in", not "ssh into". No `POST`/`GET` as verbs: "send a POST request".

## Word-list substitutions (common cases)

- above (position) → earlier / preceding
- account name → username
- abort → stop, exit, cancel, end
- access (verb) → see, edit, find, use, view
- actionable → useful / that you can act on
- app bar (Android), address bar (browser)
- blacklist → denylist; whitelist → allowlist
- master/slave → primary/replica
- man-hours → person-hours
- dummy variable → placeholder variable
- crazy/insane → baffling, unexpected
- sanity check → final check
- utilize/leverage → use
- in order to → to
- i.e. → that is; e.g. → for example; etc. → and so on
- 10x faster → 10 times faster
- approx. → approximately
- drop-down → menu
- hamburger icon / zippy → expander arrow (or name the actual control)
- omnibox → address bar

## Source

Condensed from the live guide: https://developers.google.com/style — 60+ pages including About, Highlights, Philosophy, Voice and tone, Active voice, Present tense, Second person, Sentence structure, Anthropomorphism, Articles, Abbreviations, Contractions, Pluralization, Possessives, Prepositions, Pronouns, Procedures, Accessibility, Inclusive documentation, Global audience, Excessive claims, Jargon, Prescriptive documentation, Timeless documentation, Cross-references, Notices, Text-formatting summary, Capitalization, Headings and titles, Lists, Numbers, Dates and times, Units of measurement, Code in text, Code samples, Command-line syntax, Placeholders, UI elements, API reference comments, Filenames, Examples, Product names, Italics, Quotation marks, Dashes, Hyphens, Colons, Commas, Semicolons, Slashes, Ellipses, Parentheses, Periods, Tables, Images, Footnotes, Word list. When a rule here is insufficient for an edge case, consult the live guide.