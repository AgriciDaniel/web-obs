# Publish with a look (style profiles)

A client report can carry its own look: colors, two bundled fonts, the agency name and a footer line. The Publish dialog in the audit view has a **Look** choice: **Default**, **Agency** or **Client**. This page explains the Look side (profile files, the dialog, editing, the default look setting). What a look contains, the limits, the paired upload and what is sent are in [Client reports](CLIENT-REPORTS.md#a-report-with-a-look).

## What needs which report app version

| Feature | Report app on the server |
| --- | --- |
| A report with a look, sent as the paired request | 0.1.4 or later |
| The readability check that refuses an unreadable card color | 0.1.5 or later |
| Text on cards (`cardText`, `cardMuted`) | 0.1.6 or later |
| The shared style check this plugin copies (cards drawn opaque for dark text, readable label chips, readable built in colors) | 0.1.7 (the copy in `src/report/styles/` is the 0.1.7 code) |

A report with the Default look is sent as a plain report and works with any server. A look that uses only the slots an older server knows works with that server; a look that uses `cardText` or `cardMuted` is refused by a server older than 0.1.6 (it does not know the names).

## Where the profiles live

A folder in the vault (default `<vault>/.web-obs/styles/`; change it with the setting **Style profiles folder**, a full path or a path inside the vault):

```
.web-obs/styles/
  agency.json            the agency profile (offered as "Agency: <name>")
  clients/
    example-client.com.json  one file per client (offered as "Client: <name>")
    ...
  default.json           optional; a generic look. Without it, Default means the built-in look and nothing extra is sent.
```

Client file names use letters, digits, dot, space and dash (up to 80 characters) and end in `.json`. Files are read as plain files only (not links), at most 64 KB each.

## The file shape

The home system's brand profile, as it already is. The keys used:

| Profile key | Becomes |
|---|---|
| `colors.accent_orange` (else `colors.primary`) | `accent` (buttons, dots, highlights) |
| `colors.primary` | `link` |
| `colors.blue_light` | `secondary` (the expandable explanation headings) |
| `colors.text_on_dark` | `text` |
| `colors.muted` | `muted` |
| `colors.surface` (else `colors.grey_2`) | `surface` (cards and panels) |
| `fonts.heading.name`, `fonts.body.name` | `headingFont`, `bodyFont`: only `Oswald` and `Inter` are bundled; another name is left out with a note and the system font is used |
| `fonts.heading.case` | `headingCase` (`uppercase`, `none`, `capitalize`, `lowercase`) |
| `name` | `name` (browser title) |
| `attribution.footer_text` | `footerText` (the one line naming who prepared the report) |

Everything else (`voice`, `avoid_words`, `preferences`, `audience`, `source`, `logo`, `grid`, `tint`, `blue_dark`, the reserved `grey_0` and `grey_1`, `attribution.header_text`) is never sent. The header of the viewer shows the client's name only; the agency is named once, in the footer.

A file that is already a flat styles file (`{ "accent": "#F2994A", "name": "..." }`, see the report app's `docs/STYLES.md`) is also accepted.

## What Publish does

1. The chosen file is read and turned into flat styles, then checked with the same validator the ingest and the report server use (`src/report/styles/styles.mjs`, an exact copy; `scripts/verify-report-look.mjs` checks it against the report app's sha256). A profile that needs a fix stops the publish with a plain message and nothing is sent.
2. The report is built with the look inside it. For an https target the report is sent as ONE request with two named parts, `styles_<hash>` and `data_<hash>` (the hash is the first 12 hex characters of the SHA-256 of the styles). For a folder or ssh target the report file holds the look.
3. A server older than 0.1.4 refuses that request. The dialog says so: update the report server and the ingest first, or publish with the Default look. A report with the Default look publishes to any version.
4. The dialog shows a one-line summary of the look (accent, card color, fonts), what was adjusted for readability, and a reminder that everything in a look is visible to anyone who has the report link. Put no private notes or contact details in a profile.

A look travels with its report: old links keep the look they were published with. To change it, publish again.

## Creating a profile from the dialog

Agency and the client for the captured site are always in the Look list. A choice with no file yet is marked "not set up yet"; choosing it opens a form in the Publish dialog instead of failing.

- **Fields:** name, accent, secondary, card surface (optional), text, muted, heading font, body font (Oswald, Inter or the system font), heading case, footer text. The form starts from what the capture knows about the site (name, theme color, palette, a bundled font it uses). A logo is mentioned but not sent: logos are not part of a look yet.
- **Checks:** the same validator the ingest and the report server use, with the contrast notes shown under the form.
- **Save profile** writes the file and selects it. Agency writes `agency.json`; a client writes `clients/<site-domain>.json`. The name comes from the capture's domain (lower case, letters, digits, dots and dashes only), never from the form. The file is written to a temporary name and moved into place. A link in place of the styles folder is refused. An existing file is never replaced without a second, explicit "Replace the file".
- **Cancel** returns to the dialog on Default. **Send with Default look** publishes at once with the built-in look. Nothing leaves the computer except on Publish.
- Everything in a look is visible to anyone who has the report link; the form says so.

Later: the profile source becomes the tagged client contract in the home vault. All finding and creating of profiles goes through two functions in `src/plugin/profileSource.ts` (`findProfile`, `createProfile`); swapping the source means replacing those two.

## Readability (report app 0.1.5)

The report server refuses a look whose card color is too light for the page's light text. The plugin runs the same check before anything is sent, so a profile like that is listed as "needs a fix" with a message naming the slot (for example surface), and the create form will not save it. Colors that are only a little too dim are adjusted, not refused. Use a dark card color (the page text is light).

## The create form in detail

- **Layout:** a scrolling body with the buttons pinned below it; two columns on a normal width, one on a narrow dialog. Groups: Identity (Name, Attribution footer), Colors (Accent, Secondary, Card surface, Text, Muted), Fonts (Heading font, Body font, Heading case).
- **What the fields do:** Name is shown in the browser tab title and fills the footer line (Prepared by ...) when the attribution footer is empty. Attribution footer is the line shown below the 3D presentation layer. Accent colors buttons, the active step and highlights. Secondary colors the expandable sections. Card surface is the background of cards and panels (choose a dark one). Text is the main text color; Muted is small secondary text. The page background and the 3D globe never change.
- **Color pickers:** each color has a native picker kept in step with its hex box. "Use built-in" clears a color back to the built-in value. A readability note appears next to the field it is about.
- **Buttons:** **Save profile and publish** writes the profile file and then publishes with it (if the save does not happen, nothing is published); **Save profile** only writes the file; **Send with Default look** publishes with the built-in look and saves nothing; **Cancel** goes back. The save buttons wait until the form is valid, and the ones that publish also wait for Approved by.
- **Footer default for a client:** "Prepared by <agency name>", from agency.json in the styles folder (its name field). With no agency profile the footer starts empty and a hint says so; it never uses the client's name. The client's Name still fills the browser tab title. The Agency form starts with empty Name and footer (it is not prefilled from the captured site).

## Where this form fits later

The manual create-a-profile form is the **backup path**. When the plugin is integrated with the home vault, the client look will come from the tagged client contract. All finding and creating of profiles already goes through one seam, `findProfile` and `createProfile` in `src/plugin/profileSource.ts` (and the agency name for the footer through `agencyNameFromFolder`), so the swap replaces that file only. The form, the validator and the publish path stay as they are, and the form can stay available for clients that have no contract yet.

## Editing a saved profile

When the Look is Agency or a client that already has a profile file, **Edit profile** appears next to the Look. It opens the same form, filled from the saved file (every field, card text included), with the same checks, the same **Use readable text** help and the same contrast notes.

- **Save changes** writes the file in place: a temporary file in the same folder, then a rename, so a half-written file never appears. The previous version is copied next to it as `<name>.json.bak` (one backup, replaced by each save). No other file is touched.
- **Save changes and publish** saves first and publishes second. If the save does not happen (for example the file was changed by something else after it was opened), nothing is published and the reason is shown.
- Only the fields you changed are written. Keys the form does not know are kept as they are, never run or interpreted. Clearing a field removes its key. A flat styles file stays flat; a brand-profile file keeps its own shape.
- A file that is not readable JSON, is too large (64 KB limit) or is not a plain file is reported in words and is not opened.
- **Cancel** returns to the Look. With changes not yet saved it asks first, and so does picking another Look.

The plugin settings have a **Style profiles** section that lists Agency and the clients with a one-line summary (accent, card, fonts) and any problem the check finds, with an **Edit** button. There is no delete in this version.

## The default look

The setting **Default look when publishing** decides which Look the dialog preselects. It stays visible and changeable, with a one-line note saying why it was chosen.

| Setting | Preselected |
| --- | --- |
| Client profile for this site, else the Agency profile, else Default (recommended, the default) | the client profile named after the site, else Agency, else Default |
| Agency profile | Agency, else Default |
| Default look | Default |
| Remember my last choice | the look used last time if it still exists, else the recommended order above |

A look that has no profile file yet is never preselected.

### The seam for the later home integration

The whole decision is one pure function, `resolveDefaultLook({ domain, choices, preference, lastId })` (it returns `{ id, reason }` and never throws). It is written in `src/data/defaultLook.ts` and re-exported from `src/plugin/profileSource.ts` beside `findProfile` and `createProfile`, so that the later home-vault integration, which will know the client and the agency preference, replaces this one function and nothing else. The same file exports `DEFAULT_LOOK_PREFERENCES` (the options and their labels) and `isDefaultLookPreference`. The editing functions beside it are `readProfileForEdit` and `updateProfile`.

### Report app 0.1.7: the card as drawn

The shared check is now the one from report app 0.1.7 (the plugin's copy matches it byte for byte). What changes for a look: the cards are drawn opaque when the text on them is darker than the card (so a light card reads as checked, not about 10 percent darker), the muted label chips get their own readable text color, and the built-in muted text, second color and link are nudged on a card that is not dark. The form's notes may list those adjustments. A look made with 0.1.6 still works on a 0.1.6 server; light cards read best on 0.1.7.

## Look and feel

The dialogs use Obsidian's own CSS variables (background, text, borders, accent, error and success colors), so they follow the active theme, light or dark, and community themes. Check them with `python scripts/verify-publish-dialog-ui.py` (real browser, dark and light, 1000 and 420 px wide: contrast of every text, focus ring, labels, reasons for disabled buttons, no sideways overflow) and look at them with `python scripts/render-publish-dialog-states.py <folder> [prefix]` (PNG renders of every state).

The dialogs are deliberately compact: controls are 28 px high, helper lines are one or two short lines, and a secondary explanation ("What is sent") sits behind a small toggle. `verify-publish-dialog-ui.py` checks the compactness (the whole dialog in a pane 700 px high with the form closed) and that no control is smaller than 28 px.

## Text on cards (report app 0.1.6)

The page is always dark, so Text on the page is lightened until it reads there. Text on cards is separate and is checked against the card color only, so a light card can carry dark text. Fields: **Text on the page**, **Muted on the page**, **Text on cards**, **Muted on cards** (empty: a softer shade of the card text). **Use readable text** fills Text on cards with the better of white and near-black for the chosen card color and shows the ratio. If Text on cards is left empty the page text is used on cards, exactly as before (which is why a light card without it is refused, with a message that names the colors and the numbers).

Profile mapping: `colors.text_on_dark` is the page text; `colors.text` is the text on cards when it reaches 4.5:1 on the profile's card (otherwise it is left out with a note); `colors.muted_on_card` is Muted on cards; `colors.muted` is Muted on the page. The server needs 0.1.6 or later for a look that uses these; an older server refuses the unknown names.
