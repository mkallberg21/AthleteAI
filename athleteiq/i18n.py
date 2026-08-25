"""Spanish, on the surfaces where not having it does the most damage.

A meaningful share of youth-sports families in the United States speak
Spanish at home. The places that matters most are not the leaderboard or the
drill picker -- a child navigates those from icons and numbers regardless.
They are the **parent portal, the consent flow, and the messages a child's
coach sends home**: the surfaces where a guardian is being asked to
understand something and then agree to it.

A consent screen somebody cannot read is not consent. That is the whole
argument for this file.

Three things are worth being explicit about.

**The language belongs to the person, not the program.** A Spanish-speaking
household inside an English-speaking club is the common case, not the edge
one, so the preference is per user and a guardian sets their own.

**We can translate what we ship, and not what a coach types.** The default
recognition bodies here have Spanish versions. A coach who rewrites one in
English produces English, and this module will not pretend otherwise -- there
is no translation service in this application and inventing one silently
would be worse than the gap.

**These translations are not certified.** They were written for this codebase
rather than by a professional translator, and the consent copy in particular
is legally adjacent. A program relying on it should have a native speaker read
it first; the README says so too.

Register: *usted* throughout for guardians, which is what US Spanish-language
school and club communication uses for parents. Neutral vocabulary over
regional -- an Argentine and a Mexican parent should both read it as ordinary
rather than as somebody else's dialect.
"""
from __future__ import annotations

from typing import Any

EN = "en"
ES = "es"
DEFAULT = EN

#: What a user may choose. Kept small on purpose: a half-translated language
#: in a picker is a promise the product does not keep.
LOCALES: tuple[tuple[str, str], ...] = (
    (EN, "English"),
    (ES, "Español"),
)
SUPPORTED = {code for code, _ in LOCALES}


def normalize(value: str | None) -> str:
    """Resolve anything user- or header-supplied to a locale we actually have.

    Accepts `es-MX`, `ES`, `es_419` and similar, because a browser sends
    whatever it likes and falling back to English on a tag we could have
    matched would hand a Spanish-speaking parent an English consent form.
    """
    if not value:
        return DEFAULT
    tag = value.strip().lower().replace("_", "-").split(",")[0].split(";")[0]
    if tag in SUPPORTED:
        return tag
    base = tag.split("-")[0]
    return base if base in SUPPORTED else DEFAULT


# ---------------------------------------------------------------------------
# The catalog
#
# Plain nested dicts rather than gettext: this codebase has no build step and
# no compiled artifacts, and a .mo file nobody can read in a diff is a poor
# fit for copy that gets argued over.
# ---------------------------------------------------------------------------

STRINGS: dict[str, dict[str, str]] = {
    # -- Consent -----------------------------------------------------------
    "consent.participation.label": {
        EN: "Training in the app",
        ES: "Entrenar en la aplicación",
    },
    "consent.participation.why": {
        EN: ("Your athlete can record drills and their counts are shared with "
             "their coach. Video is analysed on their phone and never uploaded."),
        ES: ("Su hijo o hija puede grabar ejercicios y sus resultados se "
             "comparten con su entrenador. El video se analiza en el teléfono "
             "y nunca se sube a internet."),
    },
    "consent.leaderboard_name.label": {
        EN: "Show their full name on team leaderboards",
        ES: "Mostrar su nombre completo en las tablas del equipo",
    },
    "consent.leaderboard_name.why": {
        EN: ("Without this they still appear and still compete, under an "
             "initial and jersey number instead of their full name."),
        ES: ("Sin esto igual aparece y sigue compitiendo, con su inicial y el "
             "número de camiseta en lugar de su nombre completo."),
    },
    "consent.coach_video.label": {
        EN: "Let a coach watch a clip your athlete chooses to send",
        ES: "Permitir que un entrenador vea un video que su hijo o hija elija enviar",
    },
    "consent.coach_video.why": {
        EN: ("Off unless you turn it on. Everywhere else in this app video "
             "stays on your athlete's phone and is never uploaded. With this "
             "on, they can choose to send one specific clip to their coach for "
             "feedback — never automatically, always one at a time. Clips are "
             "deleted after 30 days, and turning this off deletes any that are "
             "still there straight away."),
        ES: ("Está desactivado hasta que usted lo active. En el resto de la "
             "aplicación el video se queda en el teléfono y nunca se sube. Con "
             "esto activado, su hijo o hija puede elegir enviar un video "
             "específico a su entrenador para recibir comentarios: nunca de "
             "forma automática, siempre de uno en uno. Los videos se borran a "
             "los 30 días, y si usted desactiva esto se borran de inmediato."),
    },
    "consent.data_retention.label": {
        EN: "Keep detailed rep timings for 45 days",
        ES: "Guardar los tiempos detallados de cada repetición por 45 días",
    },
    "consent.data_retention.why": {
        EN: ("Used to review a disputed score. Turning this off keeps their "
             "totals and removes the rep-by-rep detail."),
        ES: ("Se usan para revisar un resultado en disputa. Si lo desactiva, se "
             "conservan los totales y se elimina el detalle repetición por "
             "repetición."),
    },
    # The household wording, where the person granting the permission and the
    # person who would watch are the same.
    "consent.family.coach_video.label": {
        EN: "Let clips your athlete sends reach your dashboard",
        ES: "Permitir que los videos que envíe su hijo o hija lleguen a su panel",
    },
    "consent.family.coach_video.why": {
        EN: ("Off unless you turn it on. Everywhere else in this app video "
             "stays on their phone. With this on, they can choose to send you "
             "one specific clip for feedback — their choice, one at a time, "
             "never automatic. It is uploaded to do that, so it is a real "
             "decision and not just a screen. Clips are deleted after 30 days, "
             "and turning this off deletes them straight away."),
        ES: ("Está desactivado hasta que usted lo active. En el resto de la "
             "aplicación el video se queda en su teléfono. Con esto activado, "
             "su hijo o hija puede elegir enviarle un video específico para "
             "recibir comentarios: es su decisión, de uno en uno, nunca "
             "automático. Para hacerlo el video sí se sube, así que es una "
             "decisión real y no solo una pantalla. Los videos se borran a los "
             "30 días, y si usted desactiva esto se borran de inmediato."),
    },

    # -- Parent portal -----------------------------------------------------
    "parent.title": {EN: "Parent portal", ES: "Portal para padres"},
    "parent.athletes": {EN: "Your athletes", ES: "Sus atletas"},
    "parent.decisions": {EN: "Decisions to make", ES: "Decisiones por tomar"},
    "parent.everything_decided": {
        EN: "Everything is decided", ES: "Ya está todo decidido"},
    "parent.away.title": {EN: "Going away", ES: "Ausencia planeada"},
    "parent.away.blurb": {
        EN: ("A holiday or a tournament weekend pauses a streak instead of "
             "breaking it. The days come out of the count rather than being "
             "added to it — they come back to the streak they earned, not a "
             "bigger one."),
        ES: ("Unas vacaciones o un fin de semana de torneo pausan la racha en "
             "lugar de romperla. Esos días salen de la cuenta en vez de "
             "sumarse: su hijo o hija vuelve a la racha que se ganó, no a una "
             "más larga."),
    },
    "parent.away.who": {EN: "Who", ES: "Quién"},
    "parent.away.from": {EN: "From", ES: "Desde"},
    "parent.away.until": {EN: "Until", ES: "Hasta"},
    "parent.away.reason": {EN: "Why (optional)", ES: "Motivo (opcional)"},
    "parent.away.add": {EN: "Add", ES: "Agregar"},
    "parent.away.none": {EN: "Nothing booked.", ES: "No hay nada programado."},
    "parent.away.remove": {EN: "Remove", ES: "Quitar"},
    "parent.report.worth_knowing": {
        EN: "Worth knowing", ES: "Vale la pena saber"},
    "parent.report.coach_said": {
        EN: "What their coach said", ES: "Lo que dijo su entrenador"},
    "parent.report.looking_after": {
        EN: "Looking after themselves", ES: "Cuidándose"},
    "parent.report.no_ranking": {
        EN: ("This is about your own child only. We do not rank children "
             "against their teammates here or anywhere else."),
        ES: ("Esto se refiere únicamente a su propio hijo o hija. No "
             "clasificamos a los niños frente a sus compañeros ni aquí ni en "
             "ningún otro lugar."),
    },
    "parent.days_trained": {EN: "days trained", ES: "días entrenados"},
    "parent.sessions": {EN: "sessions", ES: "sesiones"},
    "parent.minutes": {EN: "minutes", ES: "minutos"},
    "parent.add_athlete": {EN: "Add another athlete", ES: "Agregar otro atleta"},
    "parent.add_athlete.blurb": {
        EN: ("If you have a second child in the program, paste their invite "
             "code."),
        ES: ("Si tiene otro hijo o hija en el programa, pegue aquí su código "
             "de invitación."),
    },
    "parent.link": {EN: "Link athlete", ES: "Vincular atleta"},
    "parent.sign_out": {EN: "Sign out", ES: "Cerrar sesión"},
    "parent.language": {EN: "Language", ES: "Idioma"},

    # -- Recognition, shipped defaults only --------------------------------
    "recognition.first_session": {
        EN: ("{first_name}, that is your first one logged. The hard part is "
             "starting and you have done it — see you at practice."),
        ES: ("{first_name}, esa es tu primera sesión registrada. Lo difícil es "
             "empezar y ya lo hiciste. Nos vemos en el entrenamiento."),
    },
    "recognition.streak_3": {
        EN: ("{first_name}, three days running. That is how a habit starts, "
             "and I noticed."),
        ES: ("{first_name}, tres días seguidos. Así empieza un hábito, y me di "
             "cuenta."),
    },
    "recognition.streak_5": {
        EN: ("Five days in a row, {first_name}. Most people do not get here. "
             "Well done."),
        ES: ("Cinco días seguidos, {first_name}. Poca gente llega hasta aquí. "
             "Bien hecho."),
    },
    "recognition.streak_10": {
        EN: ("{first_name}, ten days straight. That is real work and it will "
             "show up on the field. Proud of you."),
        ES: ("{first_name}, diez días seguidos. Eso es trabajo de verdad y se "
             "va a notar en la cancha. Estoy orgulloso de ti."),
    },
    "recognition.streak_30": {
        EN: ("Thirty days, {first_name}. A month of turning up when nobody "
             "made you. That is the thing that separates players."),
        ES: ("Treinta días, {first_name}. Un mes presentándote sin que nadie te "
             "obligara. Eso es lo que distingue a un jugador."),
    },
    "recognition.streak_100": {
        EN: ("{first_name} — one hundred days. I am not sure what to say "
             "except that I have coached a long time and this is rare."),
        ES: ("{first_name}, cien días. No sé bien qué decir, salvo que llevo "
             "mucho tiempo entrenando y esto se ve muy pocas veces."),
    },
    # The parent voice. Warmer and shorter, as in English.
    "recognition.family.first_session": {
        EN: ("{first_name}, you did the first one. Starting is the hard bit, "
             "and you started."),
        ES: ("{first_name}, hiciste la primera. Lo difícil es empezar, y "
             "empezaste."),
    },
    "recognition.family.streak_3": {
        EN: ("Three days running, {first_name}. I noticed, and I am not just "
             "saying that."),
        ES: ("Tres días seguidos, {first_name}. Me di cuenta, y no lo digo por "
             "decir."),
    },
    "recognition.family.streak_5": {
        EN: ("Five days, {first_name}. You did that on your own and I am proud "
             "of you."),
        ES: ("Cinco días, {first_name}. Lo hiciste tú solo y estoy orgulloso de "
             "ti."),
    },
    "recognition.family.streak_10": {
        EN: ("Ten days straight, {first_name}. Nobody made you do any of them. "
             "That is the part that counts."),
        ES: ("Diez días seguidos, {first_name}. Nadie te obligó a ninguno. Esa "
             "es la parte que cuenta."),
    },
    "recognition.family.streak_30": {
        EN: ("A whole month, {first_name}. Thirty days of choosing to. I hope "
             "you are as pleased with that as I am."),
        ES: ("Un mes entero, {first_name}. Treinta días eligiendo hacerlo. "
             "Espero que estés tan contento con eso como lo estoy yo."),
    },
    "recognition.family.streak_100": {
        EN: ("One hundred days, {first_name}. I do not really have words for "
             "it. Well done."),
        ES: ("Cien días, {first_name}. La verdad no tengo palabras. Bien "
             "hecho."),
    },

    # -- What a coach wrote themselves -------------------------------------
    "recognition.coach_wrote_this": {
        EN: "",
        ES: ("Su entrenador escribió este mensaje. Se muestra tal como lo "
             "escribió."),
    },
}


def t(key: str, locale: str = DEFAULT, **kwargs: Any) -> str:
    """One string. Falls back to English rather than to the key.

    Showing a raw key like `consent.coach_video.why` to a parent would be
    worse than showing English, and a missing translation is a bug to fix in
    the catalog rather than something to surface on a consent form.
    """
    entry = STRINGS.get(key)
    if entry is None:
        return ""
    text = entry.get(locale) or entry.get(DEFAULT, "")
    return text.format(**kwargs) if kwargs else text


def bundle(locale: str = DEFAULT, prefix: str = "") -> dict[str, str]:
    """Every string for a locale, optionally narrowed to one surface.

    The parent portal fetches its own bundle rather than every string in the
    catalog, so a page does not ship copy it never renders.
    """
    locale = normalize(locale)
    return {
        key: (value.get(locale) or value.get(DEFAULT, ""))
        for key, value in STRINGS.items()
        if not prefix or key.startswith(prefix)
    }


def missing() -> dict[str, list[str]]:
    """Keys with no translation for a locale. Reported, not hidden.

    A half-translated language is a promise the product does not keep, so it
    is better to be able to see the gap than to discover it on a consent form.
    """
    out: dict[str, list[str]] = {}
    for code in SUPPORTED:
        gaps = [
            key for key, value in STRINGS.items()
            if not value.get(code) and value.get(DEFAULT)
        ]
        if gaps:
            out[code] = sorted(gaps)
    return out
