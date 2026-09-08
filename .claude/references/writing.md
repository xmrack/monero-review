<!-- How every report in this repository is written. Shared by all four review
     skills and by the agents whose prose reaches a report. Not Monero
     knowledge: that lives in .claude/references/monero/. -->

# How to write a review

One reader. A Monero maintainer, mid-week, with a queue of pull requests and
an afternoon. They open the report to answer three questions:

1. Is something wrong?
2. Where is it?
3. What do I change?

Everything else in the file is there to let them check your answer. A sentence
that helps with none of the three is costing you the reader's attention for
the ones that do.

Two disciplines below. Orwell's six rules are about not writing rubbish. The
Simplified Technical English rules are about writing something a tired reader
parses on the first pass. They agree more than they disagree, and where they
disagree Orwell's sixth rule settles it.

# Orwell's six rules

From "Politics and the English Language", 1946. They are the whole of it:

> 1. Never use a metaphor, simile, or other figure of speech which you are used
>    to seeing in print.
> 2. Never use a long word where a short one will do.
> 3. If it is possible to cut a word out, always cut it out.
> 4. Never use the passive where you can use the active.
> 5. Never use a foreign phrase, a scientific word, or a jargon word if you can
>    think of an everyday English equivalent.
> 6. Break any of these rules sooner than say anything outright barbarous.

## What each one means in a security report

**1. No stock figures of speech.** They arrive pre-worn and carry no
information. Cut "attack surface" where you mean a specific entry point, "low
hanging fruit", "rabbit hole", "in the wild", "belt and braces", "the elephant
in the room", "smoking gun". Say the thing.

> Before: The parser is a rich attack surface and this change opens the
> floodgates.
> After: `parse_tx` now accepts a length field the caller no longer bounds.

**2. Short words.** `use` not `utilise`. `before` not `prior to`. `can` not
`is able to`. `if` not `in the event that`. `about` not `approximately`.
`enough` not `sufficient`. `stop` not `terminate`, unless the code calls it
terminate.

**3. Cut the word.** This is the rule that fixes verbosity, and it is
mechanical: read your sentence and delete every word whose removal changes no
fact. "It is worth noting that the check is absent" is "the check is absent".
"There is no validation performed on the length" is "nothing validates the
length" — six words for eight, and it also fixes rule 4.

**4. Active voice.** Name who does it. In a security report the actor is the
whole point: "the length is not checked" hides the question a maintainer is
about to ask, which is *by whom*. Write "no caller checks the length" and cite
the callers you looked at. The passive is honest only where the actor is
genuinely unknown or irrelevant, and in a finding it is neither.

> Before: An out-of-bounds read can be triggered by a crafted response.
> After: A peer's crafted response reads past the end of the buffer.

**5. No jargon where a plain word exists.** This one needs care here, because
half of what we write is jargon that has no plain equivalent. `key image`,
`ring signature`, `scalar`, `subaddress`, `levin bucket` are the names of the
things and must not be softened. What rule 5 forbids is *our* jargon: the
vocabulary of this pipeline. A maintainer does not know what a cell, a unit, a
lens, a seam pass or an angle is, and has no reason to learn. See
**Our jargon never reaches the reader** below.

**6. Break the rules rather than write something barbarous.** A precise long
word beats a short vague one. `deserialization` is five syllables and exactly
right. If following a rule would make you misdescribe the code, follow the
code.

# Simplified Technical English

ASD-STE100 is a controlled-language specification written so that a technician
whose first language is not English can read a maintenance manual once and get
it right. Its Part 1 is 65 writing rules; its Part 2 is a dictionary of about
900 approved words, each with one approved meaning.

**We take Part 1 and not Part 2.** The dictionary is built for aircraft
maintenance and has no entry for `scalar` or `serializer`; applying it here
would be theatre. The writing rules are what transfer, and they transfer well,
because a maintainer skimming forty reports is in the same position as that
technician. The specification is licensed, so the rules below are restated in
our own words rather than copied.

## The rules that carry

**Words.** One thing keeps one name for the whole report. If you called it
`m_key_images` in the finding, do not call it "the key image map" in the fix
and "the index" in the summary — a reader cannot tell whether those are three
things. Pick the identifier and repeat it. Repetition is not a style flaw
here; it is how a reader knows two sentences are about the same object.

**Noun phrases.** No more than three nouns in a row. "co-signer key image
component count check" is five and unparseable; write "the check on the number
of key image components". Break the cluster with a preposition, even at the
cost of two words. Keep the articles: "the check", not "check".

**Verbs.** Simple tenses. Present tense for what the code does, past for what
you did. Avoid `-ing` chains: "validating the length before allocating" is
"it validates the length, then allocates". No stacked conditionals — "would
have been able to have been reached" is "a peer can reach it".

**Sentences.** One idea each. Twenty words is the cap on a sentence that tells
the reader to do something, twenty-five on a sentence that describes. Count
them when a sentence feels long; the count is usually worse than the feel. A
sentence carrying three clauses joined by dashes and a "but" is three
sentences that have not been separated yet.

> Before (53 words, one sentence): The check is arithmetically right — honest
> signers holding `C(N-1,N-M)` keys each cover the whole set once at least `M`
> of them have contributed, which `import_multisig` already enforces — but it
> is placed at the bottom of the crypto helper, and its one production caller
> invokes it in the middle of `update_multisig_rescan_info`'s mutation of
> `m_key_images`.
>
> After (three sentences, 15/8/14): The check is arithmetically right: any `M`
> signers together hold every component, and `import_multisig` already
> requires `M`. The problem is where it sits. Its one production caller runs it
> midway through `update_multisig_rescan_info`'s mutation of `m_key_images`.

Nothing was lost and the reader gets three facts instead of one blur.

**State the condition first.** "If the daemon runs with
`--enable-multisig-experimental`, a co-signer can..." — not the condition
trailing after the claim. A reader who does not meet the condition can stop at
word six.

**Do not compress by deleting words.** Telegraphic prose is not brevity.
"Length unchecked, overflow reachable" reads as notes to yourself. Write the
verbs and the articles; the sentence is two words longer and one pass faster.

**Descriptive paragraphs: six sentences, one topic, topic sentence first.**
Under our budgets you will rarely reach six.

**Vertical lists for parallel things.** Three call sites, four preconditions,
five excluded files: that is a list, not a sentence with semicolons.

# Our jargon never reaches the reader

The report is read by somebody who has never seen this repository. These words
are ours and they stay on this side of it:

| never write | write |
| --- | --- |
| unit, cell, lens | the files, the area, "what was read for" |
| angle, verifier, the panel | the plain count: `2/2 angles agreed` on the locator line, and nothing else |
| seam pass, round two, re-look, advocate | say the gap in plain words: "nothing looked across the two areas" |
| mapper, merger, the Lead | the passive is better than naming a robot |
| `coverage.unaccounted` is empty, `seamPassApplicable` false | "every changed file is accounted for", "no pass looked across areas" |
| candidate | finding, or "proposal", depending on which it is |

A field name from the workflow's returned object is never the right thing to
put in front of a maintainer. Read the value, say the fact.

The one exception is the coverage stamp, which is an HTML comment, invisible
when rendered, and written for a program. Field names belong there and nowhere
else.

# Words and phrases to cut on sight

Each of these is either a hedge, a filler, or a claim about the review rather
than about the code.

| cut | because |
| --- | --- |
| it is worth noting that, it should be noted, note that | the sentence after it is the sentence |
| arguably, essentially, effectively, fundamentally | either it is true or you have not finished checking |
| in practice, in theory | say the practice, or the theory |
| the fact that | "the fact that X is Y" is "X is Y" |
| may potentially, could possibly | one modal is enough |
| some areas may warrant further review | this is not a finding, a summary, or a gap; it is a way of writing nothing |
| careful review reveals, upon investigation, I examined | nobody is paying for an account of the review |
| significant, substantial, considerable | give the number |
| robust, proper, appropriate, adequate | name the property |
| this is not ideal, is problematic, is concerning | say what happens |
| various, several, a number of | count them |
| thoroughly verified, independently confirmed | the vote count is the evidence; an adjective is not |
| leverage, surface (verb), performant | not words |

# What the rules do not touch

- **Code.** A quoted snippet is copied exactly, whatever its style. Never
  reflow, retype or tidy a line you are citing: the reader is going to compare
  it against the file.
- **Identifiers.** `m_key_image_partial` is its name. Do not translate it into
  prose and do not correct its spelling.
- **Domain terms.** `key image`, `ring signature`, `scalar`, `subaddress`,
  `bulletproof`, `levin`, `enote`. These are the short words. There is nothing
  shorter.
- **The severity ladder.** `CRITICAL`, `HIGH`, `MEDIUM`, `LOW`, spelled that
  way, because a program reads them.
- **The coverage stamp.** A machine's line, exempt from all of the above and
  copied field for field.

# One paragraph is one line

Do not hard-wrap prose in `review.md`. A paragraph is a single long line,
however long that is; let the reader's browser wrap it.

This is not a style preference, it is where the file is read. GitHub renders a
single newline in an ISSUE BODY as a line break — a GFM extension for
user-authored content, and the opposite of how the same Markdown renders as a
file in a repository. So prose wrapped at 78 columns, which looks tidy in an
editor and correct in every `.md` file in this repository, reaches the reader as
a column of short ragged lines with the right-hand third of the page empty. It
has already shipped that way.

Which means a newline in your prose is a DELIBERATE BREAK and reads as one.
Use it where you want one and nowhere else:

- between `**Impact.**` and the `**Needs:**` line that follows it;
- between the locator lines of a merged finding, one site per line;
- between list items, table rows, and the header's three lines.

Everything else — the summary, each labelled block of a finding, a refuted
entry's explanation, a Coverage paragraph — is one line per paragraph, with a
blank line between paragraphs.

THE SPEC FILES AND THIS ONE ARE WRAPPED AT 78 COLUMNS. That is for the people
who edit them, and it is the one piece of their formatting you must not copy.
The template blocks show the shape of the report, not the shape of its lines.

Code fences, tables and the coverage stamp are unaffected: their line breaks are
structural and were never prose.

# The pass to run before you write the file

Not a suggestion — do these six things, in this order, over what you are about
to write:

1. **Find your longest sentence.** Count its words. Over 25, split it. Do this
   again on the pieces.
2. **Delete every word whose removal loses no fact.** Start with the phrases in
   the cut-on-sight table.
3. **Turn every passive into an active** unless you truly do not know who acts.
   In a finding, if you do not know who acts, that is a gap in the finding.
4. **Grep your own draft for our jargon.** unit, cell, lens, angle, seam,
   candidate, mapper, `coverage.`. Each hit is a fact you have not yet
   translated.
5. **Read the fix alone**, with the rest of the report covered. Could a
   maintainer who has not read the finding act on it? It names a file, a
   function, and a change. If it names a principle instead, it is not a fix
   yet.
6. **Unwrap every paragraph.** Each one is a single line before you save the
   file. Any newline still inside prose is a break you meant. This is last
   because it is mechanical and it is easy to undo the other four while doing
   it — check nothing else changed.

The report is finished when cutting anything else would remove a fact.
