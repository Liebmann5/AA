# Disclaimer

Read this before running AutoApply.

## AA is pre-alpha and unproven

AA has never been tagged, never been released, and has **never successfully
submitted a job application**. The most recent full live run made 18 attempts
and produced 0 submissions. It has been run to completion by exactly one person
on a small number of machines.

Treat every capability claim in this repository as provisional until
[STATUS.md](packages/auto_apply/docs/STATUS.md) marks it verified.

## No warranty

AA is provided under the MIT Licence, **"as is", without warranty of any kind**.
The authors accept no liability for any damage, loss, missed opportunity,
account suspension, or consequence of any kind arising from its use. See
[LICENSE](LICENSE).

## Terms of service are your responsibility

Many job boards, search engines and applicant tracking systems prohibit
automated access in their terms of service. **Running AA against a site may
breach that site's terms, and doing so is your decision and your
responsibility.** AA does not evaluate, interpret or accept those terms for
you, and the maintainers cannot indemnify you against the consequences.

AA does attempt to be a well-behaved client: it paces its actions, honours
robots.txt when configured to, and never floods a host. That is courtesy, not
permission.

## What AA will not do

These are design commitments, not defaults you can flip:

- **AA does not solve CAPTCHAs.** It detects them, records them as data, and
  hands control back to you.
- **AA does not fabricate claims about you.** It may reorder, emphasise and
  rephrase what you wrote. It will not invent experience, add a skill, or
  assert a credential that is not in your profile.
- **AA does not store account credentials by default.** No credential vault
  ships.
- **AA does not modify your device without asking.** It detects, informs and
  asks; it never silently downloads, patches or installs.

## Your application is your responsibility

An application AA fills is still an application **you** submitted. Review what
goes out. AA pauses at human-in-the-loop checkpoints for exactly this reason,
and enabling autonomy requires two explicit acknowledgements.

Incorrect, incomplete or misdirected applications are a foreseeable outcome of
pre-alpha automation. Do not point AA at a role you care about until you have
watched it do the same thing successfully on a role you do not.

## Data and privacy

AA is local-first. Your profile, database, logs and documents stay on your
device or your USB drive. Research collection is **opt-in, off by default**, and
gated behind versioned consent.

However: AA writes screenshots on navigation failure and logs that its PII
filter is known to scrub imperfectly. On a **shared or public machine, those
artefacts can expose your personal data to the next user.** Use portable mode,
and tear down when you are done.

## Employment outcomes

AA makes no claim to improve your chances of being hired. Volume is not
quality, and some employers penalise it. AA exists to remove typing, and to
measure a broken process — not to promise a job.

## Legal jurisdiction

Employment, automation, data protection and accessibility law vary by
jurisdiction. AA has not been reviewed for compliance in any of them. If you
plan to use AA for research involving other people, you need ethics approval
from your own institution, and it cannot be granted retroactively.
