<!-- How every report in this repository is written. Shared by every review
     skill and by the agents whose prose reaches a report. -->

# How to write a review

One reader: a Monero maintainer with a queue of pull requests. They open the
report to answer three questions:

1. Is something wrong?
2. Where is it?
3. What do I change?

Everything else in the file is there to let them check your answer. Cut a
sentence that helps with none of the three.

Two disciplines follow: Orwell's six rules ("Politics and the English
Language"), and the Simplified Technical English writing rules. Where they
disagree, Orwell's sixth rule settles it.

# Orwell's six rules

**1. Never use a figure of speech you are used to seeing in print.** Cut
"attack surface" where you mean a specific entry point, "low hanging fruit",
"rabbit hole", "in the wild", "belt and braces", "the elephant in the room",
"smoking gun". Say the thing.

> Before: The parser is a rich attack surface and this change opens the
> floodgates.
> After: `parse_tx` now accepts a length field the caller no longer bounds.

**2. Never use a long word where a short one will do.** `use` not `utilise`.
`before` not `prior to`. `can` not `is able to`. `if` not `in the event that`.
`about` not `approximately`. `enough` not `sufficient`. `stop` not
`terminate`, unless the code calls it terminate.

**3. If it is possible to cut a word out, cut it out.** Delete every word
whose removal changes no fact. "It is worth noting that the check is absent"
is "the check is absent". "There is no validation performed on the length" is
"nothing validates the length".

**4. Never use the passive where you can use the active.** Name who does it.
Write "no caller checks the length", not "the length is not checked", and cite
the callers you looked at. The passive is honest only where the actor is
unknown or irrelevant, and in a finding it is neither.

> Before: An out-of-bounds read can be triggered by a crafted response.
> After: A peer's crafted response reads past the end of the buffer.

**5. Never use a foreign phrase, a scientific word, or a jargon word if you
can think of an everyday English equivalent.** Domain names (`key image`,
`ring signature`, `scalar`, `subaddress`, `levin bucket`) stay. What rule 5
forbids is the vocabulary of this pipeline: see **Our jargon never reaches the
reader** below.

**6. Break any of these rules sooner than say anything barbarous.** A precise
long word beats a short vague one: `deserialization` is exactly right. If
following a rule would make you misdescribe the code, follow the code.

# Simplified Technical English

We apply the writing rules of ASD-STE100 Part 1, not its Part 2 dictionary.

**Words.** One thing keeps one name for the whole report. If you called it
`m_key_images` in the finding, do not call it "the key image map" in the fix
and "the index" in the summary. Pick the identifier and repeat it.

**Noun phrases.** No more than three nouns in a row. "co-signer key image
component count check" is "the check on the number of key image components".
Break the cluster with a preposition. Keep the articles: "the check", not
"check".

**Verbs.** Simple tenses. Present tense for what the code does, past for what
you did. Avoid `-ing` chains: "validating the length before allocating" is
"it validates the length, then allocates". No stacked conditionals: "would
have been able to have been reached" is "a peer can reach it".

**Sentences.** One idea each. Twenty words is the cap on a sentence that tells
the reader to do something, twenty-five on a sentence that describes. Count
them when a sentence feels long. A sentence carrying three clauses joined by
dashes and a "but" is three sentences.

**State the condition first.** "If the daemon runs with
`--enable-multisig-experimental`, a co-signer can...". Not the condition
trailing after the claim.

**Do not compress by deleting words.** "Length unchecked, overflow reachable"
is not brevity. Write the verbs and the articles.

**Descriptive paragraphs: six sentences, one topic, topic sentence first.**

**Vertical lists for parallel things.** Three call sites, four preconditions,
five excluded files: that is a list, not a sentence with semicolons.

# Our jargon never reaches the reader

| never write | write |
| --- | --- |
| unit, cell, lens | the files, the area, "what was read for" |
| angle, verifier, the panel | the plain count: `2/2 angles agreed` on the locator line, and nothing else |
| seam pass, round two, re-look, advocate | say the gap in plain words: "nothing looked across the two areas" |
| mapper, merger, the Lead | the passive is better than naming a robot |
| `coverage.unaccounted` is empty, `seamPassApplicable` false | "every changed file is accounted for", "no pass looked across areas" |
| candidate | finding, or "proposal", depending on which it is |

A field name from the workflow's returned object never goes in front of a
maintainer. Read the value, say the fact. The one exception is the coverage
stamp: field names belong there and nowhere else.

# Our files never reach the reader either

The reader has the Monero source tree and the upstream pull request, nothing
else. The run's working files are unopenable to them. Name the source in
words instead:

| never write | write |
| --- | --- |
| `PR_CONTEXT.md` | the pull request description |
| `PR_DISCUSSION.md` | the upstream discussion, or a reviewer's comment upstream |
| `PR_HISTORY.md` | the file's history, and the commit's own sha where one settles it |
| `PR_COMMITS.md` | a commit in this pull request, by its sha and subject |
| `PR_FILES.md` | the changed-file list |
| `PR_SUBMODULES.md` | the submodule bump, by its sha range |
| `RUST_DEPS.md`, `rust-deps/<path>` | the crate by name and pinned revision, then the path inside it |
| `TOOLING.md`, `tags`, `cscope.out` | what this run could and could not do, said plainly |
| `deps-include/<path>` | `/usr/include/<path>`, which is what it is a copy of |
| `review.md` | nothing. The report does not cite itself |

A line number into one of those files is worse than no citation. Quote the
sentence you are relying on instead.

Paths in the Monero tree are the opposite case: `src/net/parse.cpp:167` is
exactly what the reader wants, and `origin/base` is a real ref in their
checkout.

# Words and phrases to cut on sight

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

# No dashes for punctuation

Never write an em dash in a report: not fencing an aside, not before an
afterthought, not as the separator in a heading or a list entry. The en dash
used the same way, and a spaced `--` standing in for one, are the same
problem. A hyphen inside a name or a flag (`--enable-multisig-experimental`,
`pre-image`, `check-and-clear`) is fine.

| what the dash was doing | write instead |
| --- | --- |
| introducing the explanation of what came before it | a colon |
| fencing an aside in mid-sentence | a pair of commas, or brackets |
| bolting a second thought onto a finished sentence | a full stop, then the second sentence |
| separating a heading, a label or a list entry from what it is about | a colon |
| standing between a struck proposal and the reason it fell | a colon |
| spanning a range | a hyphen: `lines 40-58`, `2-3 sentences` |

# What the rules do not touch

- **Code.** A quoted snippet is copied exactly, whatever its style. Never
  reflow, retype or tidy a line you are citing.
- **Anything you are quoting.** A dash in a commit message, a pull request
  description, an upstream comment or an author-supplied string is part of the
  quotation. Copy it.
- **Identifiers.** `m_key_image_partial` is its name. Do not translate it into
  prose and do not correct its spelling.
- **Domain terms.** `key image`, `ring signature`, `scalar`, `subaddress`,
  `bulletproof`, `levin`, `enote`.
- **The severity ladder.** `CRITICAL`, `HIGH`, `MEDIUM`, `LOW`, spelled that
  way, because a program reads them.
- **The coverage stamp.** Exempt from all of the above and copied field for
  field.

# One paragraph is one line

Do not hard-wrap prose in `review.md`. A paragraph is a single long line,
however long that is. GitHub renders a single newline in an issue body as a
line break, so a newline in your prose is a DELIBERATE BREAK. Use one only:

- between `**Impact.**` and the `**Needs:**` line that follows it;
- between the locator lines of a merged finding, one site per line;
- between list items, table rows, and the header's three lines.

Everything else is one line per paragraph, with a blank line between
paragraphs: the summary, each labelled block of a finding, a refuted entry's
explanation, a Coverage paragraph.

THE SPEC FILES AND THIS ONE ARE WRAPPED AT 78 COLUMNS. Do not copy that. The
template blocks show the shape of the report, not the shape of its lines.

Code fences, tables and the coverage stamp are unaffected: their line breaks are
structural.

# The pass to run before you write the file

Do these six things, in this order, over what you are about to write:

1. **Find your longest sentence.** Count its words. Over 25, split it. Do this
   again on the pieces.
2. **Delete every word whose removal loses no fact.** Start with the phrases in
   the cut-on-sight table.
3. **Turn every passive into an active** unless you truly do not know who acts.
   In a finding, if you do not know who acts, that is a gap in the finding.
4. **Grep your own draft three times.** First for our jargon: unit, cell,
   lens, angle, seam, candidate, mapper, `coverage.`. Each hit is a fact you
   have not yet translated. Then for `PR_`, `RUST_DEPS`, `TOOLING`,
   `rust-deps/`, `deps-include/` and `review.md`. Each hit is a citation the
   reader cannot open; the table under *Our files never reach the reader
   either* says what to put there instead. Then for the em dash and the en
   dash. Each hit outside a quotation is a decision you have not made yet; the
   table under *No dashes for punctuation* says which mark makes it.
5. **Read the fix alone**, with the rest of the report covered. Could a
   maintainer who has not read the finding act on it? It names a file, a
   function, and a change. If it names a principle instead, it is not
   a fix yet.
6. **Unwrap every paragraph.** Each one is a single line before you save the
   file. Any newline still inside prose is a break you meant. Check nothing
   else changed while doing it.

The report is finished when cutting anything else would remove a fact.
