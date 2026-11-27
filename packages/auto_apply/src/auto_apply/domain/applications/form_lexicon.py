"""The words of application forms, by language. Data only — a translator can extend it.

This is the one home of the language knowledge the application engine
decides with (button roles, the submit rule, field types, yes/no answers,
placeholders, required/optional markers, step indicators, and the topics
only the person may answer). ``form_language.py`` holds the matching logic;
this module holds no logic at all.

**How the classes are used.** Each class is either a *safety* class or a
*permissive* class, and the difference is the whole design:

* Safety classes make AA more careful when they match: a control that may
  submit, a question only the person may answer, an answer that belongs to
  one employer, a placeholder that is not an answer. They are matched in
  **every** language at once, whatever the page says it is written in — a
  French "Envoyer" on a page that claims to be English must still stop AA.
  A false match only makes AA ask the person.
* Permissive classes let AA act on its own when they match: a "Next" it may
  click, a field type it may fill from the profile, an "optional" it may
  leave, a step indicator that shows more steps follow. They are matched
  only in the page's candidate languages (``form_language.resolve``): what
  the page declares, what its own words show, and English.

Safety: ``submit``, ``not_submit``, ``back``, ``protected``,
``company_relative``, ``answer_company_relative``, ``open_ended``,
``decline``, ``placeholder``, ``required``, ``assessment`` (a test or
assessment the person is sent to), ``must_complete`` (wording that makes
something a condition of being considered), the selection-limit words
``choose`` / ``at_most`` / ``at_least`` / ``exactly`` / ``or_more`` /
``all_that_apply`` (a limit read too tightly only makes AA ask), ``yes`` /
``no`` (matched
everywhere, and a word that means yes in one language and no in another is
refused — a pin keeps the sets disjoint).

Permissive: ``next``, ``review``, ``optional``, ``step``,
``step_connector``, and every ``field.<type>``.

**Term syntax.** A class value is one string of terms separated by ``|``.
Terms are compared after ``form_language.fold`` (Unicode NFKC, case-folded,
accents removed from Latin, Greek, Arabic and Hebrew letters, punctuation
read as a space), so write words the way a person writes them:

* ``word`` or ``two words`` — whole words, in that order;
* ``word*`` — a word that starts with ``word`` (``sponsor*``);
* ``*word*`` — ``word`` anywhere inside a word (German compounds:
  ``*behinder*`` finds "Schwerbehinderung");
* ``=Word`` — the same, but case matters (English "us" the pronoun, not
  "US" the country);
* ``!term`` — the whole text is exactly ``term`` (a lone CJK character such
  as 名, which would otherwise be found inside 会社名);
* terms written in Chinese, Japanese, Korean, Thai, Lao, Khmer or Myanmar
  script are found anywhere in the text (those scripts do not separate words
  with spaces, or attach particles to them).

**Adding a language.** Add its ISO 639-1 key with any classes you can fill
truthfully; leave out what you are unsure of — a missing word makes AA ask,
a wrong one makes it act wrongly. Record the review in ``REVIEW``. The
pins in ``tests/domain/test_form_lexicon.py`` check the syntax, that no
yes/no word conflicts, and that every word pagecomp's reader treats as
navigation or submission is known here too.

**Status.** English is the baseline AA was built and tested on. The other
languages were written by AA's maintainers from standard vocabulary and
have **not yet been reviewed by native speakers** (``REVIEW``); the
research record carries ``LEXICON_VERSION`` so any result can be traced to
the word lists that produced it.
"""

from __future__ import annotations

#: Bump on every change to the word lists; stamped into evidence records.
LEXICON_VERSION = "2026-11-26.2"

#: Who has checked each language. "baseline": built and tested with AA.
#: "unreviewed": standard vocabulary, awaiting a native speaker's review.
REVIEW: dict[str, str] = {
    "en": "baseline",
    **{k: "unreviewed" for k in (
        "de", "fr", "es", "it", "pt", "nl", "pl", "sv", "da", "nb", "fi", "cs", "tr",
        "ru", "uk", "ja", "zh", "ko", "ar", "he", "hi", "id", "vi",
    )},
}

#: Classes matched in every language (a match makes AA more careful).
SAFETY_CLASSES = frozenset({
    "submit", "not_submit", "back", "protected", "company_relative",
    "answer_company_relative", "open_ended", "decline", "placeholder", "required",
    "yes", "no", "assessment", "must_complete", "choose", "exactly",
})
#: Classes matched only in the page's candidate languages (a match lets AA act).
PERMISSIVE_CLASSES = frozenset({
    "next", "review", "optional", "step", "step_connector",
    # Words that loosen a choice limit (selection_limits): matched only in
    # the page's languages, so a look-alike word never lets AA tick more.
    "at_most", "at_least", "or_more", "all_that_apply",
})
#: Number words by language: index ``i`` is the number ``i + 1``; alternatives
#: separated by ``|``. Read with the selection-limit words ("pick the best
#: two", "wählen Sie bis zu drei"); digits are read in every language.
NUMBER_WORDS: dict[str, tuple[str, ...]] = {
    "en": ("one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"),
    "de": ("eins|ein|eine|einen", "zwei", "drei", "vier", "fünf", "sechs", "sieben", "acht",
           "neun", "zehn"),
    "fr": ("un|une", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf", "dix"),
    "es": ("uno|una|un", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve",
           "diez"),
    "it": ("uno|una|un", "due", "tre", "quattro", "cinque", "sei", "sette", "otto", "nove",
           "dieci"),
    "pt": ("um|uma", "dois|duas", "três", "quatro", "cinco", "seis", "sete", "oito", "nove",
           "dez"),
    "nl": ("een|één", "twee", "drie", "vier", "vijf", "zes", "zeven", "acht", "negen", "tien"),
}

#: Field types a lexicon may assign (``field.<type>``), pagecomp's taxonomy.
FIELD_TYPES = (
    "first_name", "last_name", "full_name", "middle_name", "email", "phone", "address",
    "city", "postal_code", "region", "country", "linkedin", "github", "website",
    "resume", "cover_letter", "salary", "start_date", "school", "degree", "employer",
    "job_title", "birth_date", "work_authorization", "sponsorship", "gender",
    "ethnicity", "veteran", "disability", "pronouns",
)

LEXICON: dict[str, dict[str, str]] = {
    # ------------------------------------------------------------------ English
    "en": {
        "next": "next|continue|proceed|forward|next step|next page|save and continue|"
                "continue to next step|save & continue",
        "back": "back|previous|prev|go back|previous step|return",
        "review": "review|preview|review application|review your application|summary",
        "submit": "submit|send|apply|apply now|finish|complete|confirm|done|"
                  "send application|submit application",
        "not_submit": "add|attach|upload|remove|delete|cancel|save draft|save for later|edit|"
                      "clear|browse|choose file|select file|sign in|log in|login|search|filter|"
                      "close|dismiss|autofill|import|use my|parse",
        "step": "step|page|stage|part|section",
        "step_connector": "of|out of",
        "assessment": "assessment*|skills test|skill test|coding test|coding challenge|"
                      "coding exercise|coding assessment|programming test|technical test|"
                      "technical exercise|online test|aptitude test|personality test|"
                      "psychometric*|cognitive test|take home|take-home|quiz*|game based|"
                      "video interview|recorded interview|one way interview|questionnaire|"
                      "work sample|work simulation|situational judg*",
        "must_complete": "must complete|must be completed|must be submitted|required to complete|"
                         "need to complete|needs to be completed|is required|are required|"
                         "mandatory|will not be considered|won t be considered|"
                         "will not be reviewed|won t be reviewed|cannot be reviewed|"
                         "can not be reviewed|cannot review|can not review|unable to review|"
                         "cannot be considered|not be able to review|incomplete applications|"
                         "before submitting|prior to submitting|before you submit|"
                         "in order to be considered|to be considered",
        "choose": "select|choose|pick|tick|check|mark|rank|list",
        "at_most": "up to|at most|maximum|maximum of|max|no more than|not more than",
        "at_least": "at least|minimum|minimum of|min|no fewer than|no less than",
        "exactly": "exactly|only",
        "or_more": "or more",
        "all_that_apply": "all that apply|all which apply|as many as apply",
        "yes": "yes|y|true|i am|i do|i will|i have|i can|agree|i agree|accept|i accept|"
               "affirmative",
        "no": "no|n|false|i am not|i do not|i don t|i will not|i won t|i have not|i cannot|"
              "i can t|decline|disagree",
        "decline": "decline|declined|prefer not*|rather not|choose not|not to disclose|"
                   "not to answer|not to say|not to specify|do not wish to*|don t wish to*|"
                   "dont wish to*|do not want to*|don t want to*|i don t wish|i do not wish",
        "placeholder": "select|select one|select an option|choose|choose one|choose an option|"
                       "please select|please choose|please select one|pick one|none selected|"
                       "select from list",
        "required": "required|mandatory|obligatory",
        "optional": "optional|not required",
        "protected": "authori*|sponsor*|visa|visas|citizen*|immigration|work permit|"
                     "right to work|eligible|eligibility|employment eligibility|gender*|"
                     "pronoun*|race|racial|ethnic*|hispanic|latin*|veteran*|military status|"
                     "disab*|accommodat*|reasonable adjustment*|adjustments|date of birth|"
                     "birth date|birthdate|birthday|born|age|over 18|under 18|18 years|"
                     "years of age|criminal|convict*|felon*|arrest*|background check|"
                     "sexual orientation|transgender|religio*|marital|relationship status|"
                     "family status|pregnan*|nationality|national origin|health condition*|"
                     "medical condition*|state of health",
        "company_relative": "here|=us|=our|=Our|=ours|=we|=We|this company|this organization|"
                            "this organisation|this employer|this team|this role|this position|"
                            "this job|this opportunity|the company|the organization|"
                            "the organisation|the business|the employer|our company|"
                            "our team|our mission|joining the team|join the team|working at|"
                            "work at|work for|knowledge of the company|know about the company|"
                            "know about us|hear about us",
        "answer_company_relative": "your company|your team|your organization|your organisation|"
                                   "your mission|your products|your product|your culture|"
                                   "your business|your clients|your customers|join you|"
                                   "work with you|work for you|working with you",
        "open_ended": "why|describe|explain|elaborate|tell us|tell me|what interests|"
                      "what excites|what attracts|what motivates|what draws|cover letter|"
                      "about yourself|motivation|in your own words|anything else|"
                      "additional information|what do you know",
        "field.first_name": "first name|first names|given name|given names|forename|forenames",
        "field.last_name": "last name|last names|surname|family name|family names",
        "field.full_name": "full name|name|your name|legal name",
        "field.middle_name": "middle name",
        "field.email": "email|e mail|email address|e mail address",
        "field.phone": "phone|telephone|mobile|mobile number|phone number|cell|cell phone",
        "field.address": "address|street|street address|address line*",
        "field.city": "city|town",
        "field.postal_code": "zip|zip code|postal code|postcode",
        "field.region": "state|province|region",
        "field.country": "country|country of residence",
        "field.linkedin": "linkedin",
        "field.github": "github",
        "field.website": "website|portfolio|personal website|homepage",
        "field.resume": "resume|cv|curriculum vitae",
        "field.cover_letter": "cover letter|motivation letter|letter of motivation",
        "field.salary": "salary|compensation|expected salary|salary expectations|desired salary",
        "field.start_date": "start date|earliest start date|availability|available to start|"
                            "notice period",
        "field.school": "school|university|college|institution",
        "field.degree": "degree|qualification|field of study|major",
        "field.employer": "employer|current employer|company name|current company",
        "field.job_title": "job title|current title|position title",
        "field.birth_date": "date of birth|birth date|birthday",
        "field.work_authorization": "work authorization|authorized to work|eligible to work|"
                                    "right to work|work permit",
        "field.sponsorship": "sponsorship|visa sponsorship|require sponsorship",
        "field.gender": "gender|sex",
        "field.ethnicity": "race|ethnicity|ethnic origin|hispanic|latino",
        "field.veteran": "veteran|protected veteran|military service",
        "field.disability": "disability|disabled",
        "field.pronouns": "pronouns|pronoun",
    },
    # ------------------------------------------------------------------- German
    "de": {
        "next": "weiter|fortfahren|nächste|nächster schritt|weiter zum nächsten schritt|"
                "speichern und weiter",
        "back": "zurück|vorherige|vorheriger schritt|zurück zum vorherigen schritt",
        "review": "überprüfen|prüfen|vorschau|zusammenfassung|angaben prüfen",
        "submit": "absenden|senden|abschicken|bewerben|jetzt bewerben|einreichen|bestätigen|"
                  "abschließen|fertig|bewerbung absenden",
        "not_submit": "hinzufügen|hochladen|anhängen|entfernen|löschen|abbrechen|"
                      "entwurf speichern|bearbeiten|durchsuchen|datei auswählen|anmelden|"
                      "einloggen|suchen|filtern|schließen|importieren",
        "step": "schritt|seite|abschnitt|teil",
        "step_connector": "von|aus",
        "assessment": "assessment*|eignungstest|einstufungstest|onlinetest|online test|"
                      "persönlichkeitstest|wissenstest|programmiertest|programmieraufgabe|"
                      "testaufgabe|fallstudie|fragebogen|videointerview|video interview",
        "must_complete": "muss ausgefüllt werden|müssen ausgefüllt werden|ist erforderlich|"
                         "sind erforderlich|verpflichtend|nicht berücksichtigt|"
                         "nicht bearbeitet|nicht geprüft|vor dem absenden|vor dem einreichen|"
                         "muss abgeschlossen|müssen abgeschlossen",
        "choose": "wählen|wähle|auswählen|ankreuzen|markieren",
        "at_most": "bis zu|höchstens|maximal|max",
        "at_least": "mindestens|min",
        "exactly": "genau",
        "or_more": "oder mehr|oder mehrere",
        "all_that_apply": "alle zutreffenden|alle, die zutreffen",
        "yes": "ja|ich bin|ich habe|stimme zu|ich stimme zu|einverstanden|zustimmen",
        "no": "nein|ich bin nicht|ich habe keine|ich habe kein|stimme nicht zu",
        "decline": "keine angabe|keine angaben|möchte ich nicht angeben|nicht angeben|"
                   "ich möchte keine angaben machen|möchte keine angabe machen",
        "placeholder": "bitte wählen|bitte auswählen|auswählen|wählen sie|bitte wählen sie|"
                       "auswahl|bitte auswahl treffen",
        "required": "pflichtfeld|pflichtfelder|erforderlich|pflicht|obligatorisch",
        "optional": "optional|freiwillig|fakultativ|keine pflicht",
        "protected": "arbeitserlaubnis|arbeitsgenehmigung|arbeitsberechtigung*|berechtigt*|"
                     "*aufenthalt*|visum|sponsor*|"
                     "staatsangehörigkeit|nationalität|staatsbürgerschaft|geschlecht|anrede|"
                     "pronomen|geburtsdatum|geburtstag|geboren|alter|*behinder*|"
                     "gleichgestellt*|religion|konfession|familienstand|herkunft|ethnisch*|"
                     "vorstraf*|führungszeugnis|schwanger*|gesundheitszustand|vorkehrung*|"
                     "nachteilsausgleich|unterstützungsbedarf",
        "company_relative": "uns|unser*|bei uns|dieses unternehmen|diesem unternehmen|"
                            "diese stelle|diese position|dieser position|das unternehmen|"
                            "dem unternehmen",
        "answer_company_relative": "ihr unternehmen|ihrem unternehmen|ihres unternehmens|"
                                   "ihr team|ihrem team|bei ihnen",
        "open_ended": "warum|weshalb|wieso|beschreiben|beschreiben sie|erläutern|erzählen sie|"
                      "motivation|anschreiben|in eigenen worten|was reizt|was motiviert|"
                      "was wissen sie",
        "field.first_name": "vorname|vornamen|rufname",
        "field.last_name": "nachname|familienname|zuname",
        "field.full_name": "name|vollständiger name|vor und nachname|vor- und nachname",
        "field.email": "e mail|email|e mail adresse|mail",
        "field.phone": "telefon|telefonnummer|handy|handynummer|mobilnummer|mobil|rufnummer",
        "field.address": "adresse|anschrift|straße|straße und hausnummer|hausnummer",
        "field.city": "stadt|ort|wohnort",
        "field.postal_code": "plz|postleitzahl",
        "field.region": "bundesland|kanton|region",
        "field.country": "land|wohnland",
        "field.website": "webseite|website|homepage|portfolio",
        "field.resume": "lebenslauf|cv",
        "field.cover_letter": "anschreiben|motivationsschreiben|bewerbungsschreiben",
        "field.salary": "gehalt|gehaltsvorstellung|gehaltswunsch|gehaltsvorstellungen|vergütung",
        "field.start_date": "eintrittsdatum|frühester eintrittstermin|eintrittstermin|"
                            "verfügbarkeit|kündigungsfrist|starttermin",
        "field.school": "hochschule|universität|schule|bildungseinrichtung",
        "field.degree": "abschluss|studiengang|studienfach",
        "field.employer": "arbeitgeber|aktueller arbeitgeber|unternehmen|firma",
        "field.job_title": "berufsbezeichnung|jobtitel|stellenbezeichnung",
        "field.birth_date": "geburtsdatum",
        "field.work_authorization": "arbeitserlaubnis|arbeitsgenehmigung",
        "field.gender": "geschlecht",
        "field.disability": "schwerbehinderung|behinderung",
    },
    # ------------------------------------------------------------------- French
    "fr": {
        "next": "suivant|continuer|étape suivante|enregistrer et continuer|page suivante",
        "back": "précédent|retour|étape précédente|page précédente",
        "review": "vérifier|aperçu|récapitulatif|relire|vérifier ma candidature",
        "submit": "envoyer|soumettre|postuler|valider|confirmer|terminer|candidater|"
                  "envoyer ma candidature|je postule",
        "not_submit": "ajouter|joindre|télécharger|téléverser|importer|supprimer|retirer|"
                      "annuler|enregistrer le brouillon|modifier|parcourir|choisir un fichier|"
                      "se connecter|connexion|rechercher|filtrer|fermer",
        "step": "étape|page|partie|section",
        "step_connector": "sur|de",
        "assessment": "assessment*|évaluation|test en ligne|test technique|test d aptitude|"
                      "test de personnalité|test psychométrique|exercice technique|"
                      "étude de cas|questionnaire|entretien vidéo|entretien video",
        "must_complete": "doit être complété|doivent être complétés|doit être rempli|"
                         "est requis|est requise|ne sera pas examinée|"
                         "ne seront pas examinées|ne pourra pas être prise en compte|"
                         "ne sera pas prise en compte|ne sera pas étudiée|"
                         "avant de soumettre|avant d envoyer",
        "choose": "sélectionnez|sélectionner|choisissez|choisir|cochez|cocher",
        "at_most": "jusqu à|au maximum|au plus|maximum|max",
        "at_least": "au moins|au minimum|minimum",
        "exactly": "exactement",
        "or_more": "ou plus",
        "all_that_apply": "toutes les réponses qui s appliquent|toutes celles qui s appliquent|"
                          "toutes les réponses applicables",
        "yes": "oui|je suis|j accepte|d accord|si",
        "no": "non|je ne suis pas|je n ai pas|je refuse",
        "decline": "je préfère ne pas répondre|préfère ne pas répondre|ne souhaite pas répondre|"
                   "je ne souhaite pas répondre|ne pas répondre|ne se prononce pas|"
                   "je préfère ne pas le dire",
        "placeholder": "sélectionner|sélectionnez|choisir|choisissez|veuillez sélectionner|"
                       "veuillez choisir|sélectionnez une option",
        "required": "obligatoire|requis|champ obligatoire",
        "optional": "facultatif|optionnel",
        "protected": "autorisation de travail|permis de travail|autorisé à travailler|"
                     "autorisée à travailler|titre de séjour|visa|parrainage|"
                     "nationalité|citoyenneté|sexe|genre|civilité|pronom*|date de naissance|"
                     "né le|née le|âge|handicap*|rqth|religion|situation familiale|état civil|"
                     "origine|ethni*|casier judiciaire|condamn*|enceinte|grossesse|état de santé|"
                     "aménagement*",
        "company_relative": "nous|notre|nos|chez nous|cette entreprise|cette société|ce poste|"
                            "l entreprise|la société",
        "answer_company_relative": "votre entreprise|votre société|votre équipe|vous rejoindre|"
                                   "votre mission",
        "open_ended": "pourquoi|décrivez|expliquez|parlez nous|présentez vous|motivation|"
                      "lettre de motivation|en quelques mots|que savez vous",
        "field.first_name": "prénom|prénoms",
        "field.last_name": "nom de famille|nom de naissance",
        "field.full_name": "nom|nom complet|nom et prénom|prénom et nom",
        "field.email": "e mail|email|courriel|adresse e mail|adresse électronique|adresse mail",
        "field.phone": "téléphone|portable|numéro de téléphone|mobile",
        "field.address": "adresse|rue|adresse postale",
        "field.city": "ville|commune|localité",
        "field.postal_code": "code postal",
        "field.region": "région|département|province",
        "field.country": "pays",
        "field.website": "site web|site internet|portfolio",
        "field.resume": "cv|curriculum vitae",
        "field.cover_letter": "lettre de motivation",
        "field.salary": "salaire|rémunération|prétentions salariales",
        "field.start_date": "date de début|disponibilité|date de disponibilité|préavis",
        "field.school": "école|université|établissement",
        "field.degree": "diplôme|formation|niveau d études",
        "field.employer": "employeur|entreprise actuelle|société actuelle",
        "field.job_title": "intitulé du poste|poste actuel|fonction",
        "field.birth_date": "date de naissance",
        "field.work_authorization": "autorisation de travail|permis de travail",
        "field.gender": "sexe|genre",
        "field.disability": "handicap",
    },
    # ------------------------------------------------------------------ Spanish
    "es": {
        "next": "siguiente|continuar|paso siguiente|guardar y continuar|página siguiente",
        "back": "atrás|anterior|volver|regresar|paso anterior",
        "review": "revisar|vista previa|resumen|revisar solicitud",
        "submit": "enviar|enviar solicitud|postular|postularme|aplicar|solicitar|confirmar|"
                  "finalizar|terminar|inscribirme|enviar candidatura",
        "not_submit": "agregar|añadir|adjuntar|subir|cargar|eliminar|quitar|borrar|cancelar|"
                      "guardar borrador|editar|examinar|seleccionar archivo|iniciar sesión|"
                      "buscar|filtrar|cerrar|importar",
        "step": "paso|página|etapa|parte|sección",
        "step_connector": "de",
        "assessment": "assessment*|evaluación|prueba técnica|prueba en línea|prueba de aptitud|"
                      "test de personalidad|prueba psicométrica|ejercicio técnico|"
                      "caso práctico|cuestionario|entrevista en video|entrevista en vídeo",
        "must_complete": "debe completar|debe ser completado|debe completarse|"
                         "es necesario completar|se requiere|no será considerada|"
                         "no será tomada en cuenta|no podrá ser revisada|no se revisará|"
                         "no será revisada|antes de enviar",
        "choose": "seleccione|selecciona|seleccionar|elija|elige|escoja|marque|marca",
        "at_most": "hasta|como máximo|máximo|max",
        "at_least": "al menos|como mínimo|mínimo",
        "exactly": "exactamente",
        "or_more": "o más",
        "all_that_apply": "todas las que correspondan|todas las que apliquen",
        "yes": "sí|si|acepto|de acuerdo|estoy de acuerdo",
        "no": "no|no acepto|no estoy de acuerdo",
        "decline": "prefiero no decir|prefiero no decirlo|prefiero no responder|"
                   "prefiero no contestar|no deseo responder|no deseo contestar|"
                   "prefiero no especificar",
        "placeholder": "seleccione|selecciona|seleccionar|elija|elige|escoja|"
                       "seleccione una opción|selecciona una opción",
        "required": "obligatorio|requerido|campo obligatorio",
        "optional": "opcional",
        "protected": "permiso de trabajo|autorización para trabajar|autorizado para trabajar|"
                     "visa|visado|patrocinio|nacionalidad|ciudadan*|sexo|género|pronombre*|"
                     "fecha de nacimiento|edad|discapacidad|minusval*|religión|estado civil|"
                     "origen|etni*|raza|antecedentes penales|embaraz*|estado de salud|ajustes razonables|"
                     "adaptacion*|adaptación",
        "company_relative": "nosotros|nuestra|nuestro|nuestros|nuestras|con nosotros|"
                            "esta empresa|este puesto|esta posición|la empresa",
        "answer_company_relative": "su empresa|tu empresa|su equipo|tu equipo|su misión|"
                                   "unirme a ustedes",
        "open_ended": "por qué|porqué|describa|describe|explique|explica|cuéntanos|cuéntenos|"
                      "motivación|carta de presentación|en tus propias palabras|qué sabes",
        "field.first_name": "primer nombre",
        "field.last_name": "apellido|apellidos|primer apellido",
        "field.full_name": "nombre|nombre completo|nombre y apellidos",
        "field.email": "correo electrónico|correo|email|e mail",
        "field.phone": "teléfono|celular|móvil|número de teléfono",
        "field.address": "dirección|domicilio|calle",
        "field.city": "ciudad|localidad|municipio|población",
        "field.postal_code": "código postal",
        "field.region": "provincia|estado|región|comunidad autónoma|departamento",
        "field.country": "país",
        "field.website": "sitio web|página web|portafolio",
        "field.resume": "currículum|curriculum|cv|hoja de vida",
        "field.cover_letter": "carta de presentación|carta de motivación",
        "field.salary": "salario|sueldo|pretensión salarial|expectativa salarial|remuneración",
        "field.start_date": "fecha de inicio|disponibilidad|fecha de incorporación",
        "field.school": "universidad|escuela|institución|centro de estudios",
        "field.degree": "titulación|título|grado|carrera",
        "field.employer": "empresa actual|empleador",
        "field.job_title": "puesto|cargo|puesto actual|cargo actual",
        "field.birth_date": "fecha de nacimiento",
        "field.work_authorization": "permiso de trabajo",
        "field.gender": "sexo|género",
        "field.disability": "discapacidad",
    },
    # ------------------------------------------------------------------ Italian
    "it": {
        "next": "avanti|successivo|continua|prosegui|passo successivo|salva e continua",
        "back": "indietro|precedente|passo precedente",
        "review": "rivedi|riepilogo|anteprima",
        "submit": "invia|inviare|candidati|invia candidatura|conferma|completa|termina|fine",
        "not_submit": "aggiungi|allega|carica|rimuovi|elimina|annulla|salva bozza|modifica|"
                      "sfoglia|scegli file|accedi|cerca|filtra|chiudi|importa",
        "step": "passo|passaggio|pagina|fase|sezione",
        "step_connector": "di|su",
        "assessment": "assessment*|valutazione|test online|test tecnico|test attitudinale|"
                      "test di personalità|esercizio tecnico|caso di studio|questionario|"
                      "colloquio video|video colloquio",
        "must_complete": "deve essere completato|devono essere completati|è obbligatorio|"
                         "è richiesto|non sarà presa in considerazione|non sarà valutata|"
                         "prima di inviare",
        "choose": "seleziona|selezionare|scegli|scegliere|spunta|indica",
        "at_most": "fino a|al massimo|massimo|max",
        "at_least": "almeno|minimo",
        "exactly": "esattamente",
        "or_more": "o più",
        "all_that_apply": "tutte quelle pertinenti|tutte le opzioni pertinenti",
        "yes": "sì|si|accetto|sono d accordo",
        "no": "no|non accetto",
        "decline": "preferisco non rispondere|preferisco non dirlo|non desidero rispondere|"
                   "preferisco non specificare",
        "placeholder": "seleziona|selezionare|scegli|scegliere|seleziona un opzione",
        "required": "obbligatorio|richiesto|campo obbligatorio",
        "optional": "facoltativo|opzionale",
        "protected": "permesso di lavoro|permesso di soggiorno|autorizzazione al lavoro|"
                     "visto di lavoro|sponsorizzazione|nazionalità|cittadinanza|sesso|genere|"
                     "pronom*|data di nascita|età|disabilità|invalidità|categorie protette|"
                     "categoria protetta|religione|stato civile|origine|etni*|razza|"
                     "casellario giudiziale|precedenti penali|gravidanza|stato di salute|"
                     "accomodament*",
        "company_relative": "noi|nostra|nostro|nostri|nostre|con noi|questa azienda|"
                            "questa posizione|questo ruolo|l azienda",
        "answer_company_relative": "la vostra azienda|vostra azienda|il vostro team|"
                                   "unirmi a voi",
        "open_ended": "perché|descrivi|descriva|spiega|spieghi|raccontaci|motivazione|"
                      "lettera di presentazione|lettera motivazionale|cosa sai",
        "field.last_name": "cognome",
        "field.full_name": "nome|nome e cognome|nome completo",
        "field.email": "email|e mail|posta elettronica|indirizzo email",
        "field.phone": "telefono|cellulare|numero di telefono",
        "field.address": "indirizzo|via|residenza",
        "field.city": "città|comune|località",
        "field.postal_code": "cap|codice postale",
        "field.region": "provincia|regione",
        "field.country": "paese|nazione",
        "field.website": "sito web|portfolio",
        "field.resume": "curriculum|cv|curriculum vitae",
        "field.cover_letter": "lettera di presentazione|lettera motivazionale",
        "field.salary": "retribuzione|stipendio|ral|aspettativa economica|"
                        "retribuzione desiderata",
        "field.start_date": "data di inizio|disponibilità|preavviso",
        "field.school": "università|scuola|istituto",
        "field.degree": "titolo di studio|laurea|diploma",
        "field.employer": "datore di lavoro|azienda attuale",
        "field.job_title": "ruolo|qualifica|posizione attuale",
        "field.birth_date": "data di nascita",
        "field.gender": "sesso|genere",
        "field.disability": "disabilità|invalidità",
    },
    # --------------------------------------------------------------- Portuguese
    "pt": {
        "next": "próximo|seguinte|continuar|avançar|próxima etapa|salvar e continuar",
        "back": "voltar|anterior|etapa anterior",
        "review": "revisar|rever|resumo|pré visualizar",
        "submit": "enviar|enviar candidatura|submeter|candidatar|candidatar se|confirmar|"
                  "finalizar|concluir",
        "not_submit": "adicionar|anexar|carregar|enviar arquivo|enviar ficheiro|remover|excluir|"
                      "apagar|cancelar|salvar rascunho|editar|procurar|escolher arquivo|entrar|"
                      "iniciar sessão|pesquisar|buscar|filtrar|fechar|importar",
        "step": "passo|etapa|página|parte|seção|secção",
        "step_connector": "de",
        "assessment": "assessment*|avaliação|teste online|teste técnico|teste de aptidão|"
                      "teste de personalidade|exercício técnico|estudo de caso|questionário|"
                      "entrevista em vídeo",
        "must_complete": "deve ser preenchido|deve ser concluído|devem ser concluídos|"
                         "é obrigatório|é necessário concluir|não será considerada|"
                         "não será avaliada|antes de enviar",
        "choose": "selecione|selecionar|escolha|escolher|marque|marcar",
        "at_most": "até|no máximo|máximo|max",
        "at_least": "pelo menos|no mínimo|mínimo",
        "exactly": "exatamente",
        "or_more": "ou mais",
        "all_that_apply": "todas as que se aplicam|todas que se aplicam",
        "yes": "sim|aceito|concordo",
        "no": "não|não aceito|não concordo",
        "decline": "prefiro não responder|prefiro não dizer|não desejo responder|"
                   "prefiro não informar|prefiro não declarar",
        "placeholder": "selecione|selecionar|seleccione|escolha|escolher|selecione uma opção",
        "required": "obrigatório|requerido|campo obrigatório",
        "optional": "opcional|facultativo",
        "protected": "autorização de trabalho|permissão de trabalho|visto de trabalho|"
                     "patrocínio|nacionalidade|cidadania|sexo|gênero|género|pronome*|"
                     "data de nascimento|idade|deficiência|pcd|religião|estado civil|origem|"
                     "etni*|raça|antecedentes criminais|gravid*|estado de saúde|adaptaç*",
        "company_relative": "nós|nossa|nosso|nossos|nossas|conosco|connosco|esta empresa|"
                            "esta vaga|a empresa",
        "answer_company_relative": "sua empresa|vossa empresa|sua equipe|vossa equipa",
        "open_ended": "por que|porquê|descreva|explique|conte nos|motivação|"
                      "carta de apresentação|o que sabe",
        "field.first_name": "primeiro nome|nome próprio",
        "field.last_name": "sobrenome|apelido|último nome",
        "field.full_name": "nome|nome completo",
        "field.email": "e mail|email|correio eletrónico|correio eletrônico",
        "field.phone": "telefone|celular|telemóvel|número de telefone",
        "field.address": "endereço|morada|rua",
        "field.city": "cidade|localidade|município",
        "field.postal_code": "cep|código postal",
        "field.region": "estado|distrito|região",
        "field.country": "país",
        "field.website": "site|website|portfólio",
        "field.resume": "currículo|curriculum|cv",
        "field.cover_letter": "carta de apresentação|carta de motivação",
        "field.salary": "salário|pretensão salarial|remuneração",
        "field.start_date": "data de início|disponibilidade",
        "field.school": "universidade|faculdade|escola|instituição",
        "field.degree": "formação|curso|graduação",
        "field.employer": "empresa atual|empregador",
        "field.job_title": "cargo|função|cargo atual",
        "field.birth_date": "data de nascimento",
        "field.gender": "sexo|gênero|género",
        "field.disability": "deficiência",
    },
    # -------------------------------------------------------------------- Dutch
    "nl": {
        "next": "volgende|doorgaan|verder|ga verder|volgende stap|opslaan en doorgaan",
        "back": "vorige|terug|vorige stap",
        "review": "controleren|overzicht|voorbeeld",
        "submit": "versturen|verzenden|indienen|solliciteren|bevestigen|afronden|voltooien|klaar",
        "not_submit": "toevoegen|bijvoegen|uploaden|verwijderen|annuleren|concept opslaan|"
                      "bewerken|bladeren|bestand kiezen|inloggen|aanmelden|zoeken|filteren|"
                      "sluiten|importeren",
        "step": "stap|pagina|deel|onderdeel",
        "step_connector": "van",
        "assessment": "assessment*|online test|vaardigheidstest|persoonlijkheidstest|"
                      "capaciteitentest|technische test|programmeeropdracht|casus|"
                      "vragenlijst|video interview|video-interview",
        "must_complete": "moet worden ingevuld|moet worden afgerond|verplicht|is vereist|"
                         "niet in behandeling|niet worden beoordeeld|voor het verzenden",
        "choose": "selecteer|kies|kiezen|vink aan|aanvinken",
        "at_most": "tot|maximaal|hooguit|max",
        "at_least": "minimaal|ten minste|minstens",
        "exactly": "precies",
        "or_more": "of meer",
        "all_that_apply": "alle die van toepassing zijn|alles wat van toepassing is",
        "yes": "ja|akkoord|ik ga akkoord",
        "no": "nee|niet akkoord",
        "decline": "zeg ik liever niet|wil ik liever niet zeggen|geen antwoord|"
                   "liever niet beantwoorden",
        "placeholder": "selecteer|kies|maak een keuze|selecteren|kies een optie",
        "required": "verplicht|vereist|verplicht veld",
        "optional": "optioneel|facultatief|niet verplicht",
        "protected": "werkvergunning|verblijfsvergunning|visum|sponsor*|nationaliteit|geslacht|"
                     "aanhef|voornaamwoord*|geboortedatum|leeftijd|beperking|handicap|religie|"
                     "geloof|burgerlijke staat|afkomst|etni*|strafblad|zwanger*|gezondheidstoestand|"
                     "aanpassing*",
        "company_relative": "ons|onze|wij|bij ons|dit bedrijf|deze functie|deze vacature|"
                            "het bedrijf",
        "answer_company_relative": "jullie bedrijf|uw bedrijf|jullie team|uw organisatie",
        "open_ended": "waarom|beschrijf|leg uit|vertel ons|vertel|motivatie|motivatiebrief|"
                      "wat weet je",
        "field.first_name": "voornaam|voornamen|roepnaam",
        "field.last_name": "achternaam|familienaam",
        "field.full_name": "naam|volledige naam",
        "field.email": "e mail|email|e mailadres",
        "field.phone": "telefoon|telefoonnummer|mobiel|mobiele nummer",
        "field.address": "adres|straat|straatnaam|huisnummer",
        "field.city": "plaats|woonplaats|stad",
        "field.postal_code": "postcode",
        "field.region": "provincie|regio",
        "field.country": "land",
        "field.website": "website|portfolio",
        "field.resume": "cv|curriculum vitae",
        "field.cover_letter": "motivatiebrief|sollicitatiebrief",
        "field.salary": "salaris|salarisindicatie|salariswens",
        "field.start_date": "startdatum|beschikbaarheid|opzegtermijn|beschikbaar per",
        "field.school": "universiteit|hogeschool|school|opleidingsinstituut",
        "field.degree": "opleiding|diploma|studierichting",
        "field.employer": "werkgever|huidige werkgever",
        "field.job_title": "functie|functietitel|huidige functie",
        "field.birth_date": "geboortedatum",
        "field.gender": "geslacht",
        "field.disability": "beperking|handicap",
    },
    # ------------------------------------------------------------------- Polish
    "pl": {
        "next": "dalej|następny|kontynuuj|następny krok|zapisz i kontynuuj",
        "back": "wstecz|poprzedni|cofnij|powrót|poprzedni krok",
        "review": "podgląd|podsumowanie|sprawdź",
        "submit": "wyślij|prześlij|aplikuj|złóż aplikację|potwierdź|zakończ|gotowe",
        "not_submit": "dodaj|załącz|prześlij plik|usuń|anuluj|zapisz wersję roboczą|edytuj|"
                      "przeglądaj|wybierz plik|zaloguj|szukaj|filtruj|zamknij|importuj",
        "step": "krok|strona|etap|część",
        "step_connector": "z|ze",
        "yes": "tak",
        "no": "nie",
        "decline": "wolę nie odpowiadać|nie chcę odpowiadać|wolę nie podawać",
        "placeholder": "wybierz|wybierz opcję",
        "required": "wymagane|obowiązkowe|pole wymagane",
        "optional": "opcjonalne|opcjonalnie|nieobowiązkowe",
        "protected": "pozwolenie na pracę|wiza|sponsor*|obywatelstwo|narodowość|płeć|zaimk*|"
                     "data urodzenia|wiek|niepełnosprawn*|religia|wyznanie|stan cywilny|"
                     "pochodzenie|etniczn*|karalność|niekaralność|ciąża|stan zdrowia|"
                     "racjonalne usprawnienia|dostosowan*",
        "company_relative": "nas|nasz*|nami|nam|ta firma|tej firmie|to stanowisko",
        "answer_company_relative": "wasza firma|waszej firmy|waszym zespole|państwa firmy",
        "open_ended": "dlaczego|opisz|wyjaśnij|opowiedz|motywacja|list motywacyjny|co wiesz",
        "field.first_name": "imię|imiona",
        "field.last_name": "nazwisko",
        "field.full_name": "imię i nazwisko",
        "field.email": "e mail|email|adres e mail|adres email",
        "field.phone": "telefon|numer telefonu|komórka",
        "field.address": "adres|ulica|adres zamieszkania",
        "field.city": "miasto|miejscowość",
        "field.postal_code": "kod pocztowy",
        "field.region": "województwo|region",
        "field.country": "kraj",
        "field.website": "strona internetowa|portfolio",
        "field.resume": "cv|życiorys",
        "field.cover_letter": "list motywacyjny",
        "field.salary": "wynagrodzenie|oczekiwania finansowe|oczekiwane wynagrodzenie",
        "field.start_date": "data rozpoczęcia|dostępność|okres wypowiedzenia",
        "field.school": "uczelnia|szkoła|uniwersytet",
        "field.degree": "wykształcenie|kierunek|stopień",
        "field.employer": "pracodawca|obecny pracodawca",
        "field.job_title": "stanowisko|obecne stanowisko",
        "field.birth_date": "data urodzenia",
        "field.gender": "płeć",
        "field.disability": "niepełnosprawność",
    },
    # ------------------------------------------------------------------ Swedish
    "sv": {
        "next": "nästa|fortsätt|vidare|nästa steg",
        "back": "tillbaka|föregående|föregående steg",
        "review": "granska|förhandsgranska|sammanfattning",
        "submit": "skicka|skicka in|ansök|bekräfta|slutför|klar|skicka ansökan",
        "not_submit": "lägg till|bifoga|ladda upp|ta bort|avbryt|spara utkast|redigera|bläddra|"
                      "välj fil|logga in|sök|filtrera|stäng|importera",
        "step": "steg|sida|del",
        "step_connector": "av",
        "yes": "ja|jag godkänner",
        "no": "nej",
        "decline": "vill inte svara|föredrar att inte svara|vill inte uppge",
        "placeholder": "välj|välj ett alternativ",
        "required": "obligatorisk|obligatoriskt|krävs",
        "optional": "valfri|valfritt|frivillig|frivilligt",
        "protected": "arbetstillstånd|uppehållstillstånd|visum|medborgarskap|nationalitet|kön|"
                     "pronomen|födelsedatum|ålder|funktionsnedsättning|funktionshinder|"
                     "religion|civilstånd|ursprung|etnicitet|belastningsregister|gravid|hälsotillstånd|"
                     "anpassning*",
        "company_relative": "oss|vår|vårt|våra|hos oss|detta företag|den här tjänsten",
        "answer_company_relative": "ert företag|ert team|er organisation",
        "open_ended": "varför|beskriv|förklara|berätta|motivering|personligt brev|vad vet du",
        "field.first_name": "förnamn",
        "field.last_name": "efternamn",
        "field.full_name": "namn|fullständigt namn",
        "field.email": "e post|e postadress|mejl|email",
        "field.phone": "telefon|telefonnummer|mobil|mobilnummer",
        "field.address": "adress|gatuadress",
        "field.city": "ort|stad|postort",
        "field.postal_code": "postnummer",
        "field.region": "län|region",
        "field.country": "land",
        "field.website": "webbplats|hemsida|portfolio",
        "field.resume": "cv|meritförteckning",
        "field.cover_letter": "personligt brev",
        "field.salary": "lön|löneanspråk|lönekrav",
        "field.start_date": "startdatum|tillträde|uppsägningstid",
        "field.school": "skola|universitet|lärosäte",
        "field.degree": "utbildning|examen",
        "field.employer": "arbetsgivare|nuvarande arbetsgivare",
        "field.job_title": "befattning|tjänst",
        "field.birth_date": "födelsedatum",
        "field.gender": "kön",
        "field.disability": "funktionsnedsättning",
    },
    # ------------------------------------------------------------------- Danish
    "da": {
        "next": "næste|fortsæt|videre|næste trin",
        "back": "tilbage|forrige|forrige trin",
        "review": "forhåndsvisning|oversigt",
        "submit": "send|indsend|ansøg|bekræft|afslut|færdig|send ansøgning",
        "not_submit": "tilføj|vedhæft|upload|fjern|slet|annuller|gem kladde|rediger|gennemse|"
                      "vælg fil|log ind|søg|filtrer|luk|importer",
        "step": "trin|side|del",
        "step_connector": "af",
        "yes": "ja|jeg accepterer",
        "no": "nej",
        "decline": "ønsker ikke at svare|vil ikke svare|foretrækker ikke at svare",
        "placeholder": "vælg|vælg en mulighed",
        "required": "påkrævet|obligatorisk",
        "optional": "valgfri|valgfrit|frivillig",
        "protected": "arbejdstilladelse|opholdstilladelse|visum|statsborgerskab|nationalitet|køn|"
                     "pronomen|fødselsdato|alder|handicap|religion|civilstand|etnicitet|"
                     "straffeattest|gravid|helbredstilstand|tilpasning*",
        "company_relative": "os|vores|hos os|denne virksomhed|denne stilling",
        "answer_company_relative": "jeres virksomhed|jeres team|jeres organisation",
        "open_ended": "hvorfor|beskriv|forklar|fortæl|motivation|ansøgning|hvad ved du",
        "field.first_name": "fornavn",
        "field.last_name": "efternavn",
        "field.full_name": "navn|fulde navn",
        "field.email": "e mail|email|e mailadresse",
        "field.phone": "telefon|telefonnummer|mobil|mobilnummer",
        "field.address": "adresse|vejnavn",
        "field.city": "by|bynavn",
        "field.postal_code": "postnummer",
        "field.region": "region",
        "field.country": "land",
        "field.resume": "cv",
        "field.cover_letter": "ansøgning|motiveret ansøgning|følgebrev",
        "field.salary": "løn|lønforventning|lønkrav",
        "field.start_date": "startdato|tiltrædelse|opsigelsesvarsel",
        "field.school": "uddannelsessted|universitet|skole",
        "field.degree": "uddannelse",
        "field.employer": "arbejdsgiver|nuværende arbejdsgiver",
        "field.job_title": "stilling|jobtitel",
        "field.birth_date": "fødselsdato",
        "field.gender": "køn",
        "field.disability": "handicap",
    },
    # ---------------------------------------------------------- Norwegian (Bokmål)
    "nb": {
        "next": "neste|fortsett|videre|neste steg",
        "back": "tilbake|forrige|forrige steg",
        "review": "se gjennom|forhåndsvis|oppsummering",
        "submit": "send|send inn|send søknad|bekreft|fullfør|ferdig",
        "not_submit": "legg til|legg ved|last opp|fjern|slett|avbryt|lagre utkast|rediger|"
                      "bla gjennom|velg fil|logg inn|søk|filtrer|lukk|importer",
        "step": "steg|trinn|side|del",
        "step_connector": "av",
        "yes": "ja|jeg godtar",
        "no": "nei",
        "decline": "ønsker ikke å svare|vil ikke svare",
        "placeholder": "velg|velg et alternativ",
        "required": "obligatorisk|påkrevd|må fylles ut",
        "optional": "valgfri|valgfritt|frivillig",
        "protected": "arbeidstillatelse|oppholdstillatelse|visum|statsborgerskap|nasjonalitet|"
                     "kjønn|pronomen|fødselsdato|alder|funksjonsnedsettelse|"
                     "nedsatt funksjonsevne|religion|sivilstand|etnisitet|politiattest|gravid|"
                     "helsetilstand|tilrettelegging",
        "company_relative": "oss|vår|vårt|våre|hos oss|denne bedriften|denne stillingen",
        "answer_company_relative": "deres bedrift|deres selskap|deres team",
        "open_ended": "hvorfor|beskriv|forklar|fortell|motivasjon|søknadsbrev|hva vet du",
        "field.first_name": "fornavn",
        "field.last_name": "etternavn",
        "field.full_name": "navn|fullt navn",
        "field.email": "e post|e postadresse|epost",
        "field.phone": "telefon|telefonnummer|mobil|mobilnummer",
        "field.address": "adresse|gateadresse",
        "field.city": "poststed|by|sted",
        "field.postal_code": "postnummer",
        "field.region": "fylke",
        "field.country": "land",
        "field.resume": "cv",
        "field.cover_letter": "søknadsbrev|søknadstekst",
        "field.salary": "lønn|lønnskrav|lønnsforventning",
        "field.start_date": "oppstart|tiltredelse|oppsigelsestid",
        "field.school": "skole|universitet|lærested",
        "field.degree": "utdanning",
        "field.employer": "arbeidsgiver|nåværende arbeidsgiver",
        "field.job_title": "stilling|stillingstittel",
        "field.birth_date": "fødselsdato",
        "field.gender": "kjønn",
    },
    # ------------------------------------------------------------------ Finnish
    "fi": {
        "next": "seuraava|jatka|eteenpäin|seuraava vaihe",
        "back": "takaisin|edellinen|edellinen vaihe",
        "review": "tarkista|esikatselu|yhteenveto",
        "submit": "lähetä|hae|hae paikkaa|vahvista|valmis|viimeistele|lähetä hakemus",
        "not_submit": "lisää|liitä|lataa|poista|peruuta|tallenna luonnos|muokkaa|selaa|"
                      "valitse tiedosto|kirjaudu|etsi|suodata|sulje|tuo",
        "step": "vaihe|sivu|osa",
        "yes": "kyllä",
        "no": "ei",
        "decline": "en halua vastata|en halua kertoa",
        "placeholder": "valitse|valitse vaihtoehto",
        "required": "pakollinen|pakollinen kenttä",
        "optional": "vapaaehtoinen",
        "protected": "työlupa|oleskelulupa|viisumi|kansalaisuus|sukupuoli|pronomini|"
                     "syntymäaika|ikä|vamma*|uskonto|siviilisääty|etninen*|rikosrekisteri*|"
                     "raskaus|terveydentila|mukautu*",
        "company_relative": "meille|meidän|meillä|meitä|meihin|tähän yritykseen|tähän tehtävään",
        "answer_company_relative": "teidän yrityksenne|yrityksenne|tiimiinne",
        "open_ended": "miksi|kuvaile|kerro|selitä|motivaatio|hakemuskirje",
        "field.first_name": "etunimi|etunimet",
        "field.last_name": "sukunimi",
        "field.full_name": "nimi|koko nimi",
        "field.email": "sähköposti|sähköpostiosoite",
        "field.phone": "puhelin|puhelinnumero|matkapuhelin",
        "field.address": "osoite|katuosoite|lähiosoite",
        "field.city": "kaupunki|paikkakunta|postitoimipaikka",
        "field.postal_code": "postinumero",
        "field.country": "maa",
        "field.resume": "cv|ansioluettelo",
        "field.cover_letter": "hakemus|saatekirje|hakemuskirje",
        "field.salary": "palkka|palkkatoive|palkkatoivomus",
        "field.start_date": "aloituspäivä|aloitusajankohta|irtisanomisaika",
        "field.school": "oppilaitos|yliopisto|koulu",
        "field.degree": "tutkinto|koulutus",
        "field.employer": "työnantaja|nykyinen työnantaja",
        "field.job_title": "tehtävänimike|nimike",
        "field.birth_date": "syntymäaika",
        "field.gender": "sukupuoli",
    },
    # -------------------------------------------------------------------- Czech
    "cs": {
        "next": "další|pokračovat|další krok",
        "back": "zpět|předchozí|předchozí krok",
        "review": "zkontrolovat|náhled|souhrn",
        "submit": "odeslat|poslat|podat|reagovat|potvrdit|dokončit|hotovo|odeslat odpověď",
        "not_submit": "přidat|přiložit|nahrát|odebrat|odstranit|smazat|zrušit|uložit koncept|"
                      "upravit|procházet|vybrat soubor|přihlásit|hledat|filtrovat|zavřít|"
                      "importovat",
        "step": "krok|strana|část",
        "step_connector": "z|ze",
        "yes": "ano",
        "no": "ne",
        "decline": "nechci odpovídat|nechci uvádět|neuvádím",
        "placeholder": "vyberte|zvolte|vyberte možnost",
        "required": "povinné|povinný|povinná",
        "optional": "nepovinné|volitelné",
        "protected": "pracovní povolení|vízum|občanství|státní příslušnost|pohlaví|zájmen*|"
                     "datum narození|věk|postižení|zdravotní postižení|náboženství|"
                     "rodinný stav|původ|etnick*|trestní rejstřík|těhotenství|zdravotní stav",
        "company_relative": "nás|naše*|náš|nám|nami|tato firma|této firmy|tato pozice",
        "answer_company_relative": "vaše firma|vaší firmy|váš tým|vaší společnosti",
        "open_ended": "proč|popište|vysvětlete|motivace|motivační dopis",
        "field.first_name": "křestní jméno",
        "field.last_name": "příjmení",
        "field.full_name": "jméno|celé jméno|jméno a příjmení",
        "field.email": "e mail|email",
        "field.phone": "telefon|telefonní číslo|mobil",
        "field.address": "adresa|ulice",
        "field.city": "město|obec",
        "field.postal_code": "psč",
        "field.region": "kraj",
        "field.country": "země|stát",
        "field.resume": "životopis|cv",
        "field.cover_letter": "motivační dopis|průvodní dopis",
        "field.salary": "plat|mzda|platové očekávání|mzdové představy",
        "field.start_date": "nástup|datum nástupu|výpovědní lhůta",
        "field.school": "škola|univerzita|vysoká škola",
        "field.degree": "vzdělání|obor",
        "field.employer": "zaměstnavatel|současný zaměstnavatel",
        "field.job_title": "pozice|pracovní pozice",
        "field.birth_date": "datum narození",
        "field.gender": "pohlaví",
    },
    # ------------------------------------------------------------------ Turkish
    "tr": {
        "next": "ileri|sonraki|devam|devam et|sonraki adım",
        "back": "geri|önceki|önceki adım",
        "review": "incele|önizleme|özet",
        "submit": "gönder|başvur|başvuru yap|başvuruyu gönder|onayla|tamamla|bitir",
        "not_submit": "ekle|yükle|kaldır|sil|iptal|taslak kaydet|düzenle|gözat|dosya seç|"
                      "giriş yap|ara|filtrele|kapat|içe aktar",
        "step": "adım|sayfa|bölüm",
        "step_connector": "adımdan|sayfadan",
        "yes": "evet",
        "no": "hayır",
        "decline": "belirtmek istemiyorum|cevaplamak istemiyorum|yanıtlamak istemiyorum",
        "placeholder": "seçiniz|seçin|lütfen seçiniz",
        "required": "zorunlu|gerekli|zorunlu alan",
        "optional": "isteğe bağlı|opsiyonel",
        "protected": "çalışma izni|vize|sponsor*|vatandaşlık|uyruk|cinsiyet|zamir*|"
                     "doğum tarihi|yaş|engel*|din|medeni hal|medeni durum|etnik|adli sicil|"
                     "sabıka|hamile|sağlık durumu|makul düzenleme",
        "company_relative": "biz|bize|bizim|bizi|bizimle|şirketimiz*|bu şirket|bu pozisyon",
        "answer_company_relative": "şirketiniz*|ekibiniz*",
        "open_ended": "neden|niçin|açıklayın|anlatın|motivasyon|ön yazı",
        "field.first_name": "ad|adınız|isim",
        "field.last_name": "soyad|soyadı|soyadınız|soyisim",
        "field.full_name": "ad soyad|adı soyadı|ad soyadı|tam ad|isim soyisim",
        "field.email": "e posta|eposta|e posta adresi|email",
        "field.phone": "telefon|cep telefonu|telefon numarası",
        "field.address": "adres",
        "field.city": "şehir|il",
        "field.postal_code": "posta kodu",
        "field.country": "ülke",
        "field.resume": "özgeçmiş|cv",
        "field.cover_letter": "ön yazı|niyet mektubu",
        "field.salary": "maaş|ücret|maaş beklentisi|ücret beklentisi",
        "field.start_date": "başlangıç tarihi|işe başlama tarihi",
        "field.school": "okul|üniversite",
        "field.degree": "bölüm|eğitim|derece",
        "field.employer": "işveren",
        "field.job_title": "pozisyon|ünvan|unvan",
        "field.birth_date": "doğum tarihi",
        "field.gender": "cinsiyet",
    },
    # ------------------------------------------------------------------ Russian
    "ru": {
        "next": "далее|дальше|следующий|продолжить|вперед|следующий шаг",
        "back": "назад|предыдущий|вернуться|предыдущий шаг",
        "review": "проверить|предпросмотр|просмотр|сводка",
        "submit": "отправить|откликнуться|подать заявку|подтвердить|завершить|готово|"
                  "отправить отклик",
        "not_submit": "добавить|прикрепить|загрузить|удалить|отмена|отменить|"
                      "сохранить черновик|редактировать|изменить|обзор|выбрать файл|войти|"
                      "поиск|найти|фильтр*|закрыть|импорт*",
        "step": "шаг|страница|этап|часть|раздел",
        "step_connector": "из",
        "yes": "да",
        "no": "нет",
        "decline": "предпочитаю не отвечать|не хочу отвечать|не указывать|не хочу указывать",
        "placeholder": "выберите|выбрать|выберите вариант",
        "required": "обязательно|обязательное|обязательные|обязательное поле",
        "optional": "необязательно|необязательное|по желанию",
        "protected": "разрешение на работу|виза|спонсор*|гражданство|национальность|пол|"
                     "местоимени*|дата рождения|возраст|инвалидност*|религи*|вероисповедани*|"
                     "семейное положение|происхождени*|этническ*|судимост*|беременн*|состояние здоровья",
        "company_relative": "нас|нам|наш*|нами|мы|эта компания|эту компанию|эта должность",
        "answer_company_relative": "ваша компания|вашей компании|вашу компанию|ваша команда|"
                                   "вашей команде",
        "open_ended": "почему|опишите|расскажите|объясните|мотивац*|сопроводительное письмо|"
                      "что вы знаете",
        "field.first_name": "имя",
        "field.last_name": "фамилия",
        "field.full_name": "фио|полное имя|имя и фамилия",
        "field.middle_name": "отчество",
        "field.email": "электронная почта|email|e mail|эл почта|почта",
        "field.phone": "телефон|мобильный телефон|номер телефона",
        "field.address": "адрес|улица",
        "field.city": "город|населенный пункт",
        "field.postal_code": "почтовый индекс|индекс",
        "field.region": "регион|область",
        "field.country": "страна",
        "field.resume": "резюме|cv",
        "field.cover_letter": "сопроводительное письмо",
        "field.salary": "зарплата|заработная плата|желаемая зарплата|оклад",
        "field.start_date": "дата начала|дата выхода|готовность приступить",
        "field.school": "учебное заведение|университет|вуз",
        "field.degree": "образование|специальность|степень",
        "field.employer": "работодатель|место работы",
        "field.job_title": "должность",
        "field.birth_date": "дата рождения",
        "field.gender": "пол",
    },
    # ---------------------------------------------------------------- Ukrainian
    "uk": {
        "next": "далі|наступний|продовжити|вперед|наступний крок",
        "back": "назад|попередній|повернутися|попередній крок",
        "review": "перевірити|попередній перегляд|підсумок",
        "submit": "надіслати|відправити|подати заявку|відгукнутися|підтвердити|завершити|"
                  "готово",
        "not_submit": "додати|прикріпити|завантажити|видалити|скасувати|зберегти чернетку|"
                      "редагувати|змінити|огляд|вибрати файл|увійти|пошук|знайти|фільтр*|"
                      "закрити|імпорт*",
        "step": "крок|сторінка|етап|частина|розділ",
        "step_connector": "з|із",
        "yes": "так",
        "no": "ні",
        "decline": "не хочу відповідати|волію не відповідати|не вказувати",
        "placeholder": "оберіть|виберіть|оберіть варіант",
        "required": "обов язково|обов язкове|обов язкове поле",
        "optional": "необов язково|за бажанням",
        "protected": "дозвіл на роботу|віза|громадянство|національність|стать|займенник*|"
                     "дата народження|вік|інвалідніст*|релігі*|сімейний стан|походженн*|"
                     "етнічн*|судимість|вагітн*|стан здоров я",
        "company_relative": "нас|нам|наш*|нами|ми|ця компанія|цю компанію|ця посада",
        "answer_company_relative": "ваша компанія|вашої компанії|ваша команда|вашій команді",
        "open_ended": "чому|опишіть|розкажіть|поясніть|мотивац*|супровідний лист",
        "field.first_name": "ім я",
        "field.last_name": "прізвище",
        "field.full_name": "піб|повне ім я",
        "field.middle_name": "по батькові",
        "field.email": "електронна пошта|email|e mail|пошта",
        "field.phone": "телефон|номер телефону",
        "field.address": "адреса|вулиця",
        "field.city": "місто|населений пункт",
        "field.postal_code": "поштовий індекс|індекс",
        "field.region": "область|регіон",
        "field.country": "країна",
        "field.resume": "резюме|cv",
        "field.cover_letter": "супровідний лист",
        "field.salary": "зарплата|заробітна плата|бажана зарплата",
        "field.start_date": "дата початку|дата виходу",
        "field.school": "навчальний заклад|університет",
        "field.degree": "освіта|спеціальність",
        "field.employer": "роботодавець|місце роботи",
        "field.job_title": "посада",
        "field.birth_date": "дата народження",
        "field.gender": "стать",
    },
    # ----------------------------------------------------------------- Japanese
    "ja": {
        "next": "次へ|次に進む|次のステップ|続ける|続行|進む",
        "back": "戻る|前へ|前に戻る|前のステップ",
        "review": "確認画面|内容確認|入力内容の確認|プレビュー|確認する",
        "submit": "送信|応募|申し込|申込|提出|登録する|完了|確定|エントリー",
        "not_submit": "追加|添付|アップロード|削除|取消|キャンセル|下書き保存|一時保存|編集|"
                      "参照|ファイルを選択|ログイン|検索|絞り込み|閉じる|インポート",
        "step": "ステップ|ページ|段階",
        "step_connector": "中|全",
        "yes": "はい",
        "no": "いいえ",
        "decline": "回答しない|答えたくない|回答を控える|回答したくない",
        "placeholder": "選択してください|選んでください|!選択",
        "required": "必須",
        "optional": "任意",
        "protected": "就労|在留資格|在留カード|ビザ|査証|国籍|性別|生年月日|年齢|障害|障がい|"
                     "宗教|婚姻|配偶者|人種|民族|前科|犯罪歴|妊娠|健康状態|配慮",
        "company_relative": "当社|弊社|私たち|わたしたち",
        "answer_company_relative": "貴社|御社",
        "open_ended": "なぜ|理由|志望動機|自己pr|説明してください|教えてください",
        "field.first_name": "!名|下の名前",
        "field.last_name": "!姓|苗字|名字",
        "field.full_name": "氏名|お名前|!名前",
        "field.email": "メールアドレス|メール|eメール|電子メール",
        "field.phone": "電話番号|電話|携帯電話|携帯番号",
        "field.address": "住所|番地",
        "field.city": "市区町村",
        "field.postal_code": "郵便番号",
        "field.region": "都道府県",
        "field.country": "!国|居住国|国名",
        "field.resume": "履歴書",
        "field.salary": "希望年収|年収|給与|希望給与",
        "field.start_date": "入社可能日|入社日|勤務開始日",
        "field.school": "学校名|大学",
        "field.degree": "学位|専攻|最終学歴",
        "field.employer": "現在の勤務先|勤務先|会社名",
        "field.job_title": "役職|職種|職位",
        "field.birth_date": "生年月日",
        "field.gender": "性別",
    },
    # ------------------------------------------------------------------ Chinese
    "zh": {
        "next": "下一步|下一页|下一頁|继续|繼續",
        "back": "上一步|返回|上一页|上一頁",
        "review": "预览|預覽",
        "submit": "提交|递交|遞交|发送|發送|申请|申請|投递|投遞|!确认|!確認|完成",
        "not_submit": "添加|新增|附加|上传|上傳|删除|刪除|移除|取消|保存草稿|编辑|編輯|浏览|"
                      "瀏覽|选择文件|選擇檔案|登录|登入|搜索|搜尋|筛选|篩選|关闭|關閉|导入|匯入",
        "step": "步骤|步驟|步|页|頁|阶段|階段",
        "step_connector": "共|中",
        "yes": "是|是的|有",
        "no": "否|不是|没有|沒有",
        "decline": "不愿透露|不願透露|不想回答|不愿回答|不願回答",
        "placeholder": "请选择|請選擇|!选择|!選擇",
        "required": "必填|必须|必須",
        "optional": "选填|選填|可选|可選",
        "protected": "工作许可|工作許可|签证|簽證|国籍|國籍|性别|性別|出生日期|年龄|年齡|残疾|"
                     "殘疾|身心障碍|身心障礙|宗教|婚姻|种族|種族|民族|犯罪|怀孕|懷孕|健康状况|健康狀況|"
                     "合理便利|合理调整|合理調整",
        "company_relative": "我们|我們|本公司",
        "answer_company_relative": "贵公司|貴公司",
        "open_ended": "为什么|為什麼|请描述|請描述|说明|說明|动机|動機|求职信|求職信|自我介绍|"
                      "自我介紹",
        "field.first_name": "!名",
        "field.last_name": "!姓|姓氏",
        "field.full_name": "姓名|全名",
        "field.email": "电子邮件|電子郵件|邮箱|郵箱|电子邮箱|電子信箱",
        "field.phone": "电话|電話|手机|手機|手机号码|联系电话|聯絡電話",
        "field.address": "地址|住址|通讯地址",
        "field.city": "城市|所在城市",
        "field.postal_code": "邮编|郵遞區號|邮政编码|郵政編碼",
        "field.region": "省份|!省",
        "field.country": "国家|國家",
        "field.resume": "简历|簡歷|履历|履歷",
        "field.cover_letter": "求职信|求職信|自荐信",
        "field.salary": "期望薪资|期望薪資|薪资|薪資|薪水|期望月薪",
        "field.start_date": "到岗时间|到職日期|可入职日期|入职时间",
        "field.school": "学校|學校|毕业院校|畢業院校|大学|大學",
        "field.degree": "学历|學歷|学位|學位|专业|專業",
        "field.employer": "当前公司|目前公司|雇主",
        "field.job_title": "职位|職位|职务|職務|职称",
        "field.birth_date": "出生日期|生日",
        "field.gender": "性别|性別",
    },
    # ------------------------------------------------------------------- Korean
    "ko": {
        "next": "다음|계속|다음 단계",
        "back": "이전|뒤로|이전 단계",
        "review": "검토|미리보기",
        "submit": "제출|보내기|전송|지원하기|!확인|완료|등록",
        "not_submit": "추가|첨부|업로드|삭제|제거|취소|임시저장|수정|편집|찾아보기|파일 선택|"
                      "로그인|검색|필터|닫기|가져오기",
        "step": "단계|페이지",
        "step_connector": "중",
        "yes": "예|네",
        "no": "아니요|아니오",
        "decline": "답변하지 않음|응답하지 않음|밝히고 싶지 않음",
        "placeholder": "선택하세요|선택해 주세요|!선택",
        "required": "필수",
        "optional": "선택사항|선택 사항",
        "protected": "비자|체류자격|국적|성별|생년월일|나이|연령|장애|종교|결혼|혼인|인종|민족|"
                     "범죄|전과|임신|건강 상태|편의",
        "company_relative": "우리|당사|저희",
        "answer_company_relative": "귀사",
        "open_ended": "왜|이유|설명|지원 동기|자기소개",
        "field.last_name": "!성",
        "field.full_name": "이름|성명|성함",
        "field.email": "이메일|전자우편|이메일 주소",
        "field.phone": "전화번호|휴대폰|휴대전화|연락처",
        "field.address": "주소",
        "field.city": "도시",
        "field.postal_code": "우편번호",
        "field.country": "국가|나라",
        "field.resume": "이력서",
        "field.salary": "희망 연봉|희망연봉|연봉|급여",
        "field.start_date": "입사 가능일|입사가능일",
        "field.school": "학교|대학교|출신학교",
        "field.degree": "학위|전공|학력",
        "field.employer": "현 직장|현재 회사|회사명|직장",
        "field.job_title": "직위|직책|직무",
        "field.birth_date": "생년월일",
        "field.gender": "성별",
    },
    # ------------------------------------------------------------------- Arabic
    "ar": {
        "next": "التالي|متابعة|استمرار|الخطوة التالية",
        "back": "السابق|رجوع|عودة|الخطوة السابقة",
        "review": "مراجعة|معاينة|ملخص",
        "submit": "إرسال|ارسال|تقديم|قدم الآن|تأكيد|إنهاء|تم",
        "not_submit": "إضافة|إرفاق|تحميل|رفع|حذف|إزالة|إلغاء|حفظ كمسودة|تعديل|تصفح|اختيار ملف|"
                      "تسجيل الدخول|بحث|تصفية|إغلاق|استيراد",
        "step": "خطوة|الخطوة|صفحة|الصفحة|مرحلة|المرحلة",
        "step_connector": "من",
        "yes": "نعم",
        "no": "لا",
        "decline": "أفضل عدم الإجابة|لا أرغب في الإجابة|أفضل عدم الإفصاح",
        "placeholder": "اختر|اختيار|الرجاء الاختيار",
        "required": "مطلوب|إلزامي|إجباري",
        "optional": "اختياري",
        "protected": "تصريح عمل|*تأشير*|كفالة|*جنس*|تاريخ الميلاد|العمر|*إعاق*|الدين|دين|"
                     "الديانة|ديانة|الحالة الاجتماعية|العرق|عرق|سجل جنائي|الحمل|حامل|"
                     "الحالة الصحية",
        "company_relative": "*شركتنا*|معنا|نحن|لدينا",
        "answer_company_relative": "*شركتكم*|فريقكم",
        "open_ended": "لماذا|صف|اشرح|أخبرنا|الدافع",
        "field.first_name": "الاسم الأول",
        "field.last_name": "اسم العائلة|الكنية",
        "field.full_name": "الاسم|الاسم الكامل",
        "field.email": "البريد الإلكتروني|البريد الالكتروني|الإيميل",
        "field.phone": "الهاتف|رقم الهاتف|الجوال|رقم الجوال|الموبايل",
        "field.address": "العنوان",
        "field.city": "المدينة",
        "field.postal_code": "الرمز البريدي",
        "field.region": "المنطقة|المحافظة|الولاية",
        "field.country": "البلد|الدولة",
        "field.resume": "السيرة الذاتية",
        "field.cover_letter": "خطاب التقديم|رسالة التغطية|خطاب تعريفي",
        "field.salary": "الراتب|الراتب المتوقع",
        "field.start_date": "تاريخ البدء|تاريخ الالتحاق",
        "field.school": "الجامعة|المدرسة",
        "field.degree": "المؤهل|الشهادة|التخصص",
        "field.employer": "جهة العمل|صاحب العمل",
        "field.job_title": "المسمى الوظيفي",
        "field.birth_date": "تاريخ الميلاد",
        "field.gender": "الجنس",
    },
    # ------------------------------------------------------------------- Hebrew
    "he": {
        "next": "הבא|המשך|לשלב הבא",
        "back": "הקודם|חזרה|חזור|לשלב הקודם",
        "review": "סקירה|תצוגה מקדימה|סיכום",
        "submit": "שלח|שליחה|הגש|הגשה|אישור|סיום|סיים|שלח מועמדות",
        "not_submit": "הוסף|הוספה|צרף|העלאה|העלה|מחק|הסר|ביטול|בטל|שמור טיוטה|ערוך|עריכה|עיון|"
                      "בחר קובץ|התחבר|כניסה|חיפוש|חפש|סינון|סגור|ייבוא",
        "step": "שלב|עמוד",
        "step_connector": "מתוך",
        "yes": "כן",
        "no": "לא",
        "decline": "מעדיף לא לענות|מעדיפה לא לענות|לא מעוניין לענות|לא מעוניינת לענות",
        "placeholder": "בחר|בחרו|בחירה|בחר אפשרות",
        "required": "חובה|שדה חובה",
        "optional": "רשות|אופציונלי",
        "protected": "אשרת עבודה|*ויזה*|*אזרחות*|לאום|לאומיות|*מגדר*|תאריך לידה|גיל|הגיל|"
                     "*מוגבלות*|*נכות*|דת|הדת|דתי|מצב משפחתי|מוצא|ממוצא|ארץ מוצא|רישום פלילי|"
                     "*הריון*|מצב בריאותי|*התאמות*",
        "company_relative": "*אצלנו*|*שלנו*|אנחנו",
        "answer_company_relative": "*שלכם*",
        "open_ended": "למה|מדוע|תאר|תארי|הסבר|ספר לנו|ספרי לנו|מוטיבציה",
        "field.first_name": "שם פרטי",
        "field.last_name": "שם משפחה",
        "field.full_name": "שם|שם מלא",
        "field.email": "דוא ל|אימייל|דואר אלקטרוני",
        "field.phone": "טלפון|נייד|מספר טלפון|טלפון נייד",
        "field.address": "כתובת|רחוב",
        "field.city": "עיר|יישוב",
        "field.postal_code": "מיקוד",
        "field.country": "מדינה|ארץ",
        "field.resume": "קורות חיים|קו ח",
        "field.cover_letter": "מכתב מקדים|מכתב פנייה",
        "field.salary": "שכר|ציפיות שכר",
        "field.start_date": "תאריך תחילת עבודה|זמינות",
        "field.school": "מוסד לימודים|אוניברסיטה",
        "field.degree": "תואר|השכלה",
        "field.employer": "מעסיק|מקום עבודה נוכחי",
        "field.job_title": "תפקיד|תפקיד נוכחי",
        "field.birth_date": "תאריך לידה",
        "field.gender": "מגדר",
    },
    # -------------------------------------------------------------------- Hindi
    "hi": {
        "next": "आगे|अगला|जारी रखें",
        "back": "पीछे|पिछला|वापस",
        "review": "समीक्षा|पूर्वावलोकन|सारांश",
        "submit": "जमा करें|सबमिट|भेजें|आवेदन करें|पुष्टि करें|पूर्ण करें",
        "not_submit": "जोड़ें|संलग्न करें|अपलोड|हटाएं|रद्द करें|संपादित करें|फ़ाइल चुनें|लॉग इन|"
                      "खोजें|बंद करें",
        "step": "चरण|पृष्ठ",
        "step_connector": "में से",
        "yes": "हाँ|हां",
        "no": "नहीं",
        "decline": "बताना नहीं चाहते|जवाब नहीं देना चाहते|बताना नहीं चाहती",
        "placeholder": "चुनें|चुनिए",
        "required": "आवश्यक|अनिवार्य",
        "optional": "वैकल्पिक",
        "protected": "कार्य अनुमति|वीज़ा|वीजा|नागरिकता|राष्ट्रीयता|लिंग|जन्म तिथि|आयु|उम्र|"
                     "विकलांगता|दिव्यांग|धर्म|वैवाहिक स्थिति|जाति|आपराधिक|गर्भावस्था|स्वास्थ्य स्थिति",
        "company_relative": "हमारी|हमारे|हमें|हम",
        "answer_company_relative": "आपकी कंपनी|आपके संगठन",
        "open_ended": "क्यों|वर्णन|बताएं|समझाएं",
        "field.first_name": "पहला नाम",
        "field.last_name": "उपनाम|अंतिम नाम",
        "field.full_name": "नाम|पूरा नाम",
        "field.email": "ईमेल|ई मेल",
        "field.phone": "फ़ोन|फोन|मोबाइल|मोबाइल नंबर|फ़ोन नंबर",
        "field.address": "पता",
        "field.city": "शहर",
        "field.postal_code": "पिन कोड|पिनकोड",
        "field.region": "राज्य",
        "field.country": "देश",
        "field.resume": "बायोडाटा|रिज्यूमे|सीवी",
        "field.salary": "वेतन|अपेक्षित वेतन",
        "field.school": "विश्वविद्यालय|कॉलेज|विद्यालय",
        "field.degree": "डिग्री|शिक्षा",
        "field.employer": "नियोक्ता",
        "field.job_title": "पद|पदनाम",
        "field.birth_date": "जन्म तिथि|जन्मतिथि",
        "field.gender": "लिंग",
    },
    # --------------------------------------------------------------- Indonesian
    "id": {
        "next": "berikutnya|selanjutnya|lanjut|lanjutkan",
        "back": "kembali|sebelumnya",
        "review": "tinjau|pratinjau|ringkasan",
        "submit": "kirim|ajukan|lamar|kirim lamaran|konfirmasi|selesai",
        "not_submit": "tambah|tambahkan|lampirkan|unggah|hapus|batal|batalkan|simpan draf|ubah|"
                      "telusuri|pilih file|masuk|cari|saring|tutup|impor",
        "step": "langkah|halaman|tahap|bagian",
        "step_connector": "dari",
        "yes": "ya|iya",
        "no": "tidak",
        "decline": "tidak ingin menjawab|memilih tidak menjawab|tidak ingin memberitahu",
        "placeholder": "pilih|silakan pilih",
        "required": "wajib|harus diisi|wajib diisi",
        "optional": "opsional|tidak wajib",
        "protected": "izin kerja|visa|sponsor*|kewarganegaraan|jenis kelamin|tanggal lahir|usia|"
                     "umur|disabilitas|difabel|agama|status pernikahan|suku|ras|"
                     "catatan kriminal|hamil|kondisi kesehatan|akomodasi",
        "company_relative": "kami|perusahaan ini|posisi ini",
        "answer_company_relative": "perusahaan anda|tim anda",
        "open_ended": "mengapa|kenapa|jelaskan|ceritakan|motivasi|surat lamaran",
        "field.first_name": "nama depan",
        "field.last_name": "nama belakang",
        "field.full_name": "nama|nama lengkap",
        "field.email": "email|surel|alamat email",
        "field.phone": "telepon|nomor telepon|ponsel|no hp|nomor hp",
        "field.address": "alamat",
        "field.city": "kota",
        "field.postal_code": "kode pos",
        "field.region": "provinsi",
        "field.country": "negara",
        "field.resume": "cv|riwayat hidup|daftar riwayat hidup",
        "field.cover_letter": "surat lamaran|surat pengantar",
        "field.salary": "gaji|gaji yang diharapkan|ekspektasi gaji",
        "field.start_date": "tanggal mulai|ketersediaan",
        "field.school": "universitas|sekolah|institusi",
        "field.degree": "pendidikan|jurusan|gelar",
        "field.employer": "perusahaan saat ini|pemberi kerja",
        "field.job_title": "jabatan|posisi",
        "field.birth_date": "tanggal lahir",
        "field.gender": "jenis kelamin",
    },
    # --------------------------------------------------------------- Vietnamese
    "vi": {
        "next": "tiếp|tiếp theo|tiếp tục|bước tiếp theo",
        "back": "quay lại|trở lại|bước trước",
        "review": "xem lại|xem trước|tóm tắt",
        "submit": "gửi|nộp|nộp hồ sơ|ứng tuyển|xác nhận|hoàn tất|hoàn thành",
        "not_submit": "thêm|đính kèm|tải lên|xóa|hủy|lưu nháp|chỉnh sửa|sửa|chọn tệp|đăng nhập|"
                      "tìm kiếm|lọc|đóng",
        "step": "bước|trang|phần|giai đoạn",
        "step_connector": "trên",
        "yes": "có",
        "no": "không",
        "decline": "không muốn trả lời|không muốn tiết lộ",
        "placeholder": "chọn|vui lòng chọn",
        "required": "bắt buộc",
        "optional": "không bắt buộc|tùy chọn",
        "protected": "giấy phép lao động|thị thực|quốc tịch|giới tính|ngày sinh|tuổi|"
                     "khuyết tật|tôn giáo|tình trạng hôn nhân|dân tộc|tiền án|mang thai|"
                     "tình trạng sức khỏe",
        "company_relative": "chúng tôi|công ty chúng tôi|công ty này",
        "answer_company_relative": "công ty của bạn|quý công ty",
        "open_ended": "tại sao|vì sao|mô tả|giải thích|động lực",
        "field.first_name": "tên",
        "field.last_name": "họ",
        "field.full_name": "họ và tên|họ tên|tên đầy đủ",
        "field.email": "email|thư điện tử",
        "field.phone": "điện thoại|số điện thoại|di động",
        "field.address": "địa chỉ",
        "field.city": "thành phố",
        "field.postal_code": "mã bưu điện|mã bưu chính",
        "field.country": "quốc gia",
        "field.resume": "cv|sơ yếu lý lịch",
        "field.cover_letter": "thư xin việc",
        "field.salary": "mức lương|lương mong muốn|mức lương mong muốn",
        "field.start_date": "ngày bắt đầu|ngày có thể bắt đầu",
        "field.school": "trường|trường học|đại học",
        "field.degree": "bằng cấp|trình độ học vấn|chuyên ngành",
        "field.employer": "công ty hiện tại",
        "field.job_title": "chức danh|chức vụ",
        "field.birth_date": "ngày sinh",
        "field.gender": "giới tính",
    },
}

#: Writing systems a language is commonly written in: a page in one of these
#: scripts makes its languages candidates even without a ``lang`` attribute.
SCRIPT_LANGUAGES: dict[str, tuple[str, ...]] = {
    "HANGUL": ("ko",),
    "HIRAGANA": ("ja",),
    "KATAKANA": ("ja",),
    "CJK": ("zh", "ja"),
    "ARABIC": ("ar",),
    "HEBREW": ("he",),
    "DEVANAGARI": ("hi",),
    "CYRILLIC": ("ru", "uk"),
}

#: Language tags a page may declare that mean a lexicon above.
LANGUAGE_ALIASES: dict[str, str] = {
    "no": "nb", "nn": "nb", "iw": "he", "in": "id", "ji": "yi",
}

__all__ = [
    "FIELD_TYPES", "LANGUAGE_ALIASES", "LEXICON", "LEXICON_VERSION", "PERMISSIVE_CLASSES",
    "REVIEW", "SAFETY_CLASSES", "SCRIPT_LANGUAGES",
]
