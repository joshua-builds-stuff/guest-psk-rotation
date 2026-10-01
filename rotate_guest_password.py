#!/usr/bin/env python3
"""
Rotate Guest WiFi Password (Juniper Mist)
=========================================

Unattended rotation of a Mist guest captive-portal password.

Reads the WLAN selected during setup (see setup_guest_wlan.py) from
`.env`, pulls that WLAN's current JSON, and replaces the guest
portal password with a single randomly chosen, school-safe English word
(e.g. "apples", "rainbow", "penguin"). It then PUTs only the `portal`
object (with the new password) back, and GETs the WLAN again to confirm.

Provided as is, without warranty of any kind; not an official Hewlett
Packard Enterprise (HPE) product and not supported by HPE or HPE Juniper
Networking (formerly Juniper Networks). This tool MODIFIES the selected
guest WLAN (PUT) - scope the API token narrowly and test with --dry-run.

Design goals (per project requirements):
  * 100% independent / pure Python: STANDARD LIBRARY ONLY (no pip installs).
  * No Internet access of any kind except the Mist API calls themselves.
  * Runs FULLY UNATTENDED (no prompts) so it can be scheduled
    (Windows Task Scheduler / cron) to auto-rotate the password.

The new password is *meant to be shared with guests*, so it is written to:
  * stdout (captured by the scheduler),
  * password_history.log  (append-only audit trail, timestamped),
  * current_password.txt  (latest password, overwritten each run),
so staff can always find the current guest password.
If enabled at setup (MIST_BACKUP_JSON), a timestamped backup of the
pre-change WLAN JSON is saved under backups/. Backups are OFF by default.

The API TOKEN is a secret and is NEVER written to any log or file here.

Exit codes (for schedulers):
  0  success (password rotated, or dry-run completed)
  1  configuration / environment error (missing .env or fields)
  2  validation error (WLAN is not a guest 'password' portal, or
     portal.passphrase_enabled is not true)
  3  Mist API / network error. A non-empty success body that is not
     JSON is this case (one ERROR line, no traceback, body omitted),
     including --dry-run. See README.md.
"""

import argparse
import http.client
import json
import os
import secrets
import socket
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

# --------------------------------------------------------------------------- #
# Configuration / constants
# --------------------------------------------------------------------------- #

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_ENV_PATH = SCRIPT_DIR / ".env"
BACKUP_DIR = SCRIPT_DIR / "backups"
HISTORY_LOG = SCRIPT_DIR / "password_history.log"
CURRENT_PASSWORD_FILE = SCRIPT_DIR / "current_password.txt"
LOCK_FILE = SCRIPT_DIR / "rotate.lock"

API_TIMEOUT = 30  # seconds

# Allowlisted Mist cloud API hostnames (SSRF guard). Mirrors the 12 regional
# clouds published in the Mist OpenAPI spec / your standard env_handler.
_ALLOWED_HOSTS = frozenset({
    "api.mist.com", "api.gc1.mist.com", "api.ac2.mist.com", "api.gc2.mist.com",
    "api.gc4.mist.com", "api.eu.mist.com", "api.gc3.mist.com", "api.ac6.mist.com",
    "api.gc6.mist.com", "api.ac5.mist.com", "api.gc5.mist.com", "api.gc7.mist.com",
})

# --------------------------------------------------------------------------- #
# Word list: 1200 single, wholesome, easy-to-remember English words.
# Curated and adversarially screened for a K-12 school environment: no
# profanity, no proper nouns/brands, nothing that reads as inappropriate.
# Every word is lowercase a-z and at least 6 letters long. One is the new
# password each run.
# --------------------------------------------------------------------------- #

_WORDS = sorted(set("""
aardvark    academy    acorns    actress    adhesive    agenda    airfield    airplane
airship    alligator    allspice    almonds    alphabet    amethyst    ammonite    amphibian
amphibious    anchovy    angelfish    aniseed    announcer    anteater    antenna    antlion
apparel    apples    appliance    apricots    aquamarines    aquifer    arctic    armband
artichoke    artist    asparagus    astronaut    astronomy    atmosphere    audience    autumnal
avocado    baboon    backhand    backwater    badger    bagels    bagpipes    bakery
balance    ballad    bamboo    bananas    bandicoot    bangle    bantam    barber
barley    barnyard    barrel    basalt    baseline    basket    baskets    bassoon
bathrobe    bathtub    batting    beading    beaker    beaming    beanie    beanpods
beansprouts    bedroll    bedsheet    beehive    beetroot    begonia    berries    bilberry
binoculars    birdbath    birthstone    biscotti    biscuits    blackberries    blackbird    blackcurrant
blastoff    bleating    blending    blinds    blocks    blossom    blossoming    blouse
bluebells    blueberry    bluegill    blustery    boathouse    bobsled    bonito    bookcase
bookshelf    bookstore    boulder    bouncing    bouquet    bowerbird    boxcar    boxfish
boysenberry    bramble    branches    breadbox    breadstick    breezy    bridge    brightness
brittle    broccolini    brontosaurus    broomstick    brownies    brownstone    bubble    bubbles
buckeye    buckthorn    buffalo    builder    bulldog    bulletin    bullfrog    bullsnake
bungalow    bunting    burrowed    bushel    butter    buttercup    butterfly    buttery
buttons    cabbage    cabinet    cafeteria    caimans    calculator    calendula    calves
camouflage    campfire    camping    campus    candle    cannoli    cantaloupe    canteen
canyon    capsicums    capybara    caramel    caraway    cardamom    cardigan    cardstock
caribou    carnation    carousel    carpet    carport    carrot    cartoonist    carving
cashew    cashier    cassava    cassowary    castle    catamaran    caterpillar    cattle
cavefish    cavemen    caverns    celery    cellar    centipede    chairlift    chameleon
chandelier    charades    checkers    cheerleading    chestnut    chicken    chickpea    chicory
chimes    chimpanzee    chipmunk    chives    chopsticks    churros    cilantro    cinnamon
citrus    classroom    clearing    clementines    clifftop    climber    clipboard    clothes
clothespin    cloudberry    cloudlet    cloudy    clovers    clownfish    cluster    coaster
cobalt    cobblestone    coconut    cocoon    coffee    collage    collards    college
colorful    comforter    compose    compost    concert    condor    coneflower    conifer
continent    cooker    cooking    cooler    coppery    corduroy    corkboard    cornbread
corncobs    cornflakes    cornflower    cornsilk    corridor    cosmos    cottage    counselor
counter    countryside    courgettes    courtyard    cowbell    cowgirl    coyote    cradle
cranberry    crawfish    crawling    crayon    creamer    creatures    creeping    crescent
cricket    crimson    croaking    crockery    crocodiles    croissant    crossing    crouton
cruiser    crumpet    crystalline    cucumber    cupboard    cupcakes    curlew    currant
current    cushion    cutlery    cycling    cyclone    cymbals    daffodil    daisies
damselfly    damsons    dandelion    daybreak    daypack    dazzling    decorator    desert
dessert    dewberry    diagram    diamonds    digger    dinette    dinosaurs    dipper
discovery    dishcloth    dishrag    dishware    dispenser    distant    doghouse    dollhouse
dominoes    donkeys    doodlebug    doormat    dormitory    doughnut    downbeat    downpour
dragonflies    dragonfruit    drapery    drawers    dresser    dribbling    driftwood    driveway
drizzly    drumbeat    drumming    duckling    dugong    dumpling    dungarees    dustpan
earmuffs    earrings    earwig    eclipse    eggbeater    eggtimer    electric    electron
elephant    emerald    encore    endives    engine    enormous    envelope    equinox
erasers    escalator    eucalyptus    evergreen    excavation    exercise    explorer    extinct
eyeglasses    factory    fantail    farmhouse    fastball    feather    feathers    feldspar
fences    fennel    ferryboat    fiddler    fielder    figurine    filefish    firefly
fireplace    fisher    flamingo    flapjack    flatbread    flatland    flatworm    flaxseed
flipper    floating    floret    flounder    flowerbed    flowerpot    flowery    flurry
flutter    folders    football    foothills    footprint    footstool    forecast    forest
formula    fossilized    fountain    foxhound    freezer    freighter    fridge    fritter
froglets    frosty    funnel    gadwall    galaxies    galena    gallery    galloping
gander    garage    gardenia    garfish    garlands    garment    garnets    gazelle
gemstone    gentle    geranium    geyser    gigantic    gingerbread    ginkgo    giraffe
glaciers    glider    glimmer    glitter    gloves    glowworm    goalie    goblet
goldcrest    goldenrod    goldfish    golfer    gooseberries    gopher    gosling    gourds
grackle    granola    grapefruits    graphite    grasshopper    grater    gravity    greenery
greenhouse    greenstone    grocer    groundhog    grouse    guitar    gumtree    gymnast
gypsum    habitats    haddock    hadrosaurs    hailstorm    hairbrush    hairpin    hallway
hamper    handball    handout    hanger    hardwood    harmonica    harness    harvest
hatchback    hatching    hatchlings    hayfield    hayride    hazelnut    headboard    headlamp
headphone    heathland    helicopter    helmet    hematite    henhouse    herbivores    herring
hickory    highland    highway    hillock    hilltop    history    hogfish    homework
honeybun    honeydew    hoodie    hopping    horizon    hornbill    hornet    horseradish
horseshoe    houseboat    hovercraft    humidity    hummingbird    hurdles    iceberg    icicle
iguanodon    impala    indigo    inkwell    insect    instructor    interstellar    ironstone
island    jacket    jackfruits    jaguar    jasper    jellybean    jetliner    jeweler
jewels    jingle    joggers    journal    juggler    juicer    jumper    jumprope
junction    jungle    juniper    kangaroo    katydid    kerchief    kettle    keychain
kickball    kimono    kingfish    kingsnake    kitten    knapsack    knitter    knitwear
lacewing    ladder    ladybird    ladyfinger    lagoon    lakebed    lakeshore    laminate
landform    landscape    lantern    laptop    larkspur    launchpad    laurel    leapfrog
learner    leaves    legumes    lemming    lemons    leopard    lettering    lettuce
librarian    licorice    liftoff    lighthouse    lightyear    lilypad    limestone    limpet
lingonberry    linseed    liquid    lizard    loafers    lobster    locket    locust
logwood    lollipops    loquat    lorikeet    lovely    lullaby    luminous    lunchbox
lupine    lychees    lyrical    macaron    machine    magazine    magnet    magnetite
magnifier    magnolia    mahogany    mailman    malachite    mallet    mammoth    manager
mandarin    mandolin    manger    mangos    mansion    mantis    marathon    marbles
marigolds    marina    marker    market    marmoset    maroon    marshland    marten
marzipan    masking    mastodon    mattress    meadow    meadows    meander    mechanic
meerkat    melodic    mentor    meteorite    metronome    microscope    midnight    milking
millet    mincer    minerals    minivan    mirror    mitten    mixture    mockingbird
mohair    molecule    molting    monitor    monorail    moonbeam    moonflower    moonrise
moonset    moonstones    moorhen    morning    mosasaurus    motorbike    mountain    mountaintop
mudflat    muffin    muffler    mulberry    mushroom    musical    muskmelon    muskrat
mustard    narrator    nature    nebula    necktie    nectar    nectarines    nesting
nettle    nibble    nightfall    nightingale    nightstand    nimbus    notation    notepad
numbers    nuthatch    nuzzle    oatbran    oatmeal    obsidian    ocelot    octopus
omnibus    opener    opossum    oranges    orangutan    orbiting    orchestra    oregano
oriole    osprey    outdoor    outline    overalls    overcoat    overture    oyster
paddleboat    paddling    paintbox    painter    pajamas    palette    pancake    pangolin
panther    papaya    paperclip    parachute    parfait    parrot    parsley    parsnips
passing    pastels    pasture    pattern    pawpaw    peachy    peanut    peapod
pearls    pebbles    pecking    peekaboo    pelican    pencil    pendant    peninsula
peppercorn    peppers    percussion    periscope    persimmon    pestle    petticoat    pewter
photon    piccolo    picture    piglet    pigment    pillow    pilotfish    pimentos
pimientos    pineapple    pinecone    pinkish    pintail    pipefish    pitcher    placemat
planetarium    planetoid    plankton    plantain    planter    plated    platinum    platypus
playground    playpen    plumber    pogostick    polecat    pollen    pomegranates    pomelos
pompoms    pondweed    poodle    poplar    poppies    porridge    postcard    potato
potholder    prairie    prehistoric    pretty    pretzels    primitive    primroses    printer
producer    programmer    propeller    protractor    publisher    puddle    pufferfish    pulley
pulsar    pumpkins    purple    pushcart    puzzle    pyrite    quartz    quartzite
quaver    quilting    quinces    quintet    rabbits    racquet    radiant    radishes
railcar    railway    rainbow    raincoat    rainforest    rainwater    rancher    rapids
raspberry    reaction    reading    recliner    redbud    reddish    redwing    referee
refrigerator    reporter    reptiles    reservoir    rhinestone    rhubarb    ribbons    riddles
risotto    riverbed    riverside    roaster    rocket    rocking    roller    roofer
rooster    rosebuds    rosemary    rotation    rowing    rucksack    runner    runway
rutabaga    saddle    saffron    sailing    salamander    salmon    sandals    sandbank
sandbox    sandhill    sandstone    sapphire    sardine    sassafras    satsuma    saucepan
sauropod    savanna    scaled    scallion    scallop    scarecrow    scarves    scholar
scientist    scones    scoring    scraper    sculptor    scurry    seabird    seacoast
seafront    seahorse    seascape    seashells    seaside    seasons    secretary    seedcake
seedlings    semolina    serenade    server    sesame    setter    shading    shallot
shallows    shamrocks    shawls    sheepdog    shelter    shelving    sherbet    shining
shoelace    shortbread    shovel    shower    showery    shrimp    shuttle    sidewalk
silkworm    silverfish    silvery    singer    singsong    skateboard    skating    sketchpad
skillet    skinks    skipping    skylight    skyscraper    slalom    sledge    sleigh
slippers    slithered    snakes    snapper    sneakers    snorkeling    snowbank    snowcap
snowdrop    snowfall    snowman    snowmobile    snowstorm    soapstone    soccer    softball
solitaire    solstice    somersault    songbook    sorbet    sorrel    sourdough    soybean
spacecraft    spaceport    spacesuit    spaniel    sparrow    speaker    species    speckled
speedboat    spelling    spinner    sponge    sponges    spotted    spring    sprinkle
sprinter    sprout    spruce    squashes    squirmy    stable    stacking    stagecoach
stallion    stapler    stardust    starfruit    stargazer    starling    station    steamer
stellar    stencils    sticker    stickleback    stingray    stockings    stomping    stovetop
stratus    strawberry    streambed    streams    stretch    string    striped    student
subject    subway    sultana    summit    sunbeam    sunburst    sunfish    sunflowers
sunlight    sunset    sunspot    supernova    surfboard    surveyor    swampland    swampy
sweater    sweatshirt    sweetgum    swimmer    swimsuit    symphony    tablespoon    tabletop
tadpole    tailor    tamarinds    tangelo    tangerine    tanker    tapioca    tassel
teabread    teacher    teakettle    teapot    telescope    template    termite    terracotta
terrarium    textbook    theater    theropod    thimbleberry    thread    thunder    tickle
tidepool    tiramisu    toaster    toffee    tomatillos    tomatoes    topazes    toucan
townhouse    tracksuit    trailer    trainer    tramcar    tramway    traveler    treadmill
treble    treefrogs    treeline    treetops    triassic    tributary    tricycle    trilobite
trivet    trolleybus    trophy    trotting    trousers    truffle    trumpeter    tulips
tumbling    tuneful    tuning    turbot    turmeric    turnips    turnovers    turtleneck
tuxedo    typist    umpire    unearth    uniform    upbeat    urchin    utensils
valley    varnish    vegetable    veggie    vehicle    verbena    village    violets
vocalist    volcanoes    voltage    waddle    waffle    wagtail    waistcoat    waitress
walleye    walnut    walrus    warble    wardrobe    warmer    wasabi    waterbug
watercourse    watercress    watermelon    watershed    waterway    waxwing    weasel    weathervane
weaving    weevil    welder    wetlands    wheatear    wheatgerm    wheelchair    whisker
whisks    whistling    whitefish    wiggle    wiggly    wildflower    willow    windmill
windowsill    windsurfing    winged    wintry    wombat    woodland    woolen    workbook
workout    workshop    wriggle    wristband    writing    yellow    zester    zippers
""".split()))


# --------------------------------------------------------------------------- #
# Environment loading
# --------------------------------------------------------------------------- #

def parse_env_file(env_path: Path) -> dict:
    """Parse a simple KEY=VALUE .env file into a dict (ignores # comments)."""
    env_vars = {}
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env_vars[key.strip()] = value.strip()
    return env_vars


def load_config(env_path: Path) -> dict:
    """Load and validate required settings from .env."""
    if not env_path.exists():
        _die(1, f"Configuration file not found: {env_path}\n"
                f"Run setup_guest_wlan.py first to create it.")

    env = parse_env_file(env_path)
    required = ("MIST_API_URL", "MIST_API_TOKEN", "MIST_ORG_ID", "MIST_WLAN_ID")
    missing = [k for k in required if not env.get(k)]
    if missing:
        _die(1, f".env is missing required field(s): {', '.join(missing)}\n"
                f"Re-run setup_guest_wlan.py to (re)generate it.")

    api_url = env["MIST_API_URL"].rstrip("/")
    host = urlparse(api_url).hostname or ""
    if host not in _ALLOWED_HOSTS:
        _die(1, f"MIST_API_URL host '{host}' is not a recognized Mist cloud.")

    return {
        "api_url": api_url,
        "token": env["MIST_API_TOKEN"],
        "org_id": env["MIST_ORG_ID"],
        "wlan_id": env["MIST_WLAN_ID"],
        "ssid": env.get("MIST_WLAN_SSID", ""),
        # Optional: whether to save a JSON backup before each change (off by default).
        "backup_json": env.get("MIST_BACKUP_JSON", "").strip().lower()
                       in ("1", "true", "yes", "on"),
    }


# --------------------------------------------------------------------------- #
# Mist API (stdlib urllib only)
# --------------------------------------------------------------------------- #

def mist_request(method: str, api_url: str, token: str, path: str, body=None):
    """Perform a Mist API request. Returns (status_code, parsed_json_or_text).

    Raises RuntimeError on connection-level failures.
    """
    url = f"{api_url}/api/v1{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Token {token}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=API_TIMEOUT) as resp:
            raw = resp.read()
            try:
                parsed = json.loads(raw) if raw else None
            except ValueError:
                raise RuntimeError(
                    f"Mist API returned a non-JSON response (HTTP {resp.getcode()}) "
                    f"for {method} {path}.") from None
            return resp.getcode(), parsed
    except urllib.error.HTTPError as e:
        try:
            raw = e.read()
        except (OSError, http.client.HTTPException) as read_err:
            raise RuntimeError(
                f"Connection error reaching Mist API: "
                f"{type(read_err).__name__}: {read_err}") from None
        try:
            detail = json.loads(raw)
        except Exception:
            detail = raw.decode("utf-8", errors="replace")[:500]
        return e.code, detail
    except urllib.error.URLError as e:
        raise RuntimeError(f"Connection error reaching Mist API: {e.reason}")
    except (TimeoutError, socket.timeout):
        raise RuntimeError(
            f"Timed out after {API_TIMEOUT}s waiting for the Mist API to respond.")
    except (OSError, http.client.HTTPException) as e:
        raise RuntimeError(
            f"Connection error reaching Mist API: {type(e).__name__}: {e}")


def get_wlan(cfg: dict) -> dict:
    """GET the current WLAN JSON. Exits on API error."""
    status, body = mist_request(
        "GET", cfg["api_url"], cfg["token"],
        f"/orgs/{cfg['org_id']}/wlans/{cfg['wlan_id']}",
    )
    if status == 200 and isinstance(body, dict):
        return body
    if status == 401:
        _die(3, "Mist API authentication failed (invalid or expired token).")
    if status == 404:
        _die(3, f"WLAN {cfg['wlan_id']} not found in org {cfg['org_id']}.")
    _die(3, f"Failed to GET WLAN (HTTP {status}): {_short(body)}")


def put_portal_password(cfg: dict, portal: dict, new_password: str) -> dict:
    """PUT only the WLAN's `portal` object with the new password.

    Mist's PUT leaves omitted top-level fields untouched, so sending just
    `portal` avoids writing back a stale snapshot of every other setting.
    The rest of the portal dict is copied from the GET in case Mist replaces
    nested objects wholesale. Exits on API error.
    """
    payload = {"portal": dict(portal, password=new_password)}
    status, body = mist_request(
        "PUT", cfg["api_url"], cfg["token"],
        f"/orgs/{cfg['org_id']}/wlans/{cfg['wlan_id']}",
        body=payload,
    )
    if status == 200 and isinstance(body, dict):
        return body
    _die(3, f"Failed to update WLAN (HTTP {status}): {_short(body)}")


# --------------------------------------------------------------------------- #
# Core logic
# --------------------------------------------------------------------------- #

GUEST_WIFI_PASSWORD = "Guest WiFi password"
PORTAL_PASSPHRASE = "captive-portal passphrase"


def validate_guest_portal(wlan_obj: dict) -> str:
    """Ensure this WLAN is a guest 'password' captive portal, else exit.

    Returns what portal.password is for guests: GUEST_WIFI_PASSWORD on an
    open SSID, otherwise PORTAL_PASSPHRASE (after warning that auth.psk is
    left unchanged).
    """
    portal = wlan_obj.get("portal") or {}
    auth = portal.get("auth")
    if auth != "password":
        _die(2, f"This is NOT a guest portal SSID: portal.auth is "
                f"{auth!r}, expected 'password'. Aborting; nothing changed.")
    if portal.get("passphrase_enabled") is not True:
        _die(2, "portal.passphrase_enabled is not true, so guests are not "
                "asked for portal.password. Enable the passphrase on the "
                "portal in Mist first. Aborting; nothing changed.")
    auth_type = (wlan_obj.get("auth") or {}).get("type")
    if auth_type == "open":
        return GUEST_WIFI_PASSWORD
    print(f"WARNING: auth.type is {auth_type!r}, not 'open'. Only the "
          f"captive-portal passphrase (portal.password) is rotated; the Wi-Fi "
          f"passphrase in auth.psk was NOT changed and must not be replaced "
          f"with the portal word.", file=sys.stderr)
    return PORTAL_PASSPHRASE


def generate_password() -> str:
    """Return one random, school-safe, memorable English word."""
    return secrets.choice(_WORDS)


def _chmod_secret(path: Path) -> None:
    """Restrict an existing secret file (best effort on Windows)."""
    try:
        os.chmod(path, 0o600)
    except OSError:
        if os.name != "nt":
            raise


def _atomic_write_text(path: Path, content: str) -> None:
    """Write `content` to a temp file, then os.replace() it over `path`."""
    tmp = path.parent / f"{path.name}.{os.getpid()}.tmp"
    try:
        with os.fdopen(os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600),
                       "w", encoding="utf-8") as f:
            _chmod_secret(tmp)
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        _chmod_secret(path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def record_new_password(ssid: str, password: str, wlan_id: str = "",
                        kind: str = PORTAL_PASSPHRASE) -> None:
    """Persist the new (shareable) password to local files for staff.

    current_password.txt keeps the password on the first line, followed by
    what kind of secret it is and the SSID and WLAN id it belongs to so a
    leftover file is self-describing.
    It is replaced atomically and written before the history line, so the
    file staff read never lags behind the history.
    Raises OSError naming the file that could not be written.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    content = (f"{password}\n"
               f"# Kind: {kind}\n"
               f"# SSID: {ssid}\n"
               f"# WLAN ID: {wlan_id}\n"
               f"# Set: {timestamp}\n")
    try:
        _atomic_write_text(CURRENT_PASSWORD_FILE, content)
    except OSError as e:
        raise OSError(f"could not write {CURRENT_PASSWORD_FILE}: {e}") from e
    try:
        if HISTORY_LOG.exists():
            _chmod_secret(HISTORY_LOG)
        with os.fdopen(os.open(HISTORY_LOG, os.O_CREAT | os.O_WRONLY | os.O_APPEND,
                               0o600), "a", encoding="utf-8") as f:
            _chmod_secret(HISTORY_LOG)
            f.write(f"{timestamp}\t{ssid}\t{password}\n")
        _chmod_secret(HISTORY_LOG)
    except OSError as e:
        raise OSError(f"could not append {HISTORY_LOG}: {e}") from e


def save_backup(ssid: str, wlan_obj: dict) -> Path:
    """Save a timestamped backup of the pre-change WLAN JSON."""
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    safe_ssid = "".join(c if c.isalnum() else "_" for c in (ssid or "wlan"))
    path = BACKUP_DIR / f"{safe_ssid}_{stamp}.json"
    with os.fdopen(os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600),
                   "w", encoding="utf-8") as f:
        _chmod_secret(path)
        json.dump(wlan_obj, f, indent=2)
    _chmod_secret(path)
    return path


def acquire_rotation_lock():
    """Take an exclusive, non-blocking lock on LOCK_FILE, or exit 1.

    The returned file object must stay open for the whole rotation; the OS
    releases the lock when it is closed or the process exits.
    """
    f = open(LOCK_FILE, "a+", encoding="utf-8")
    try:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        try:
            f.seek(0)
            holder = f.read().strip() or "unknown holder"
        except OSError:
            holder = "unknown holder"
        f.close()
        _die(1, f"Another rotation is already running ({holder}; lock file "
                f"{LOCK_FILE}). Not starting a second one.")
    f.seek(0)
    f.truncate()
    f.write(f"pid {os.getpid()} started "
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    f.flush()
    return f


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _short(body) -> str:
    """Compact representation of an API error body (never leaks the token)."""
    if isinstance(body, (dict, list)):
        return json.dumps(body)[:300]
    return str(body)[:300]


def _die(code: int, message: str):
    """Print an error to stderr and exit with the given code."""
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(code)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rotate a Mist guest captive-portal password to a random "
                    "school-safe word. Runs unattended; safe for scheduling.")
    parser.add_argument(
        "--env", type=Path, default=DEFAULT_ENV_PATH,
        help=f"Path to the env file (default: {DEFAULT_ENV_PATH.name} next to this script).")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show the new password that WOULD be set, but do not change Mist.")
    backup_grp = parser.add_mutually_exclusive_group()
    backup_grp.add_argument(
        "--backup", dest="backup", action="store_true",
        help="Save a JSON backup of the WLAN before changing it (overrides .env).")
    backup_grp.add_argument(
        "--no-backup", dest="backup", action="store_false",
        help="Do not save a JSON backup (overrides .env).")
    parser.set_defaults(backup=None)
    args = parser.parse_args()

    cfg = load_config(args.env)
    # CLI flag wins over the .env preference; default comes from setup.
    do_backup = cfg["backup_json"] if args.backup is None else args.backup

    # Serialize real rotations: hold the lock from the GET until the local
    # password files are written, so overlapping runs cannot leave
    # current_password.txt on a word Mist has already replaced.
    lock = None if args.dry_run else acquire_rotation_lock()

    # Setup takes the same lock to change the managed WLAN. If it did so
    # between our first read and the lock, do not rotate the previous WLAN.
    if lock is not None:
        locked_wlan_id = load_config(args.env)["wlan_id"]
        if locked_wlan_id != cfg["wlan_id"]:
            _die(1, f"MIST_WLAN_ID in {args.env} changed from "
                    f"{cfg['wlan_id']} to {locked_wlan_id} while waiting for "
                    f"the lock (setup ran). Nothing was changed; run the "
                    f"rotation again.")

    # 1. Pull current WLAN JSON.
    wlan = get_wlan(cfg)
    ssid = wlan.get("ssid") or cfg["ssid"] or cfg["wlan_id"]

    # 2. Safety guard: must be a guest 'password' portal.
    kind = validate_guest_portal(wlan)

    old_password = (wlan.get("portal") or {}).get("password")
    new_password = generate_password()
    # Avoid handing out the same word twice in a row.
    while new_password == old_password:
        new_password = generate_password()

    if args.dry_run:
        print(f"[DRY RUN] SSID '{ssid}': would set new {kind} -> {new_password}")
        print("[DRY RUN] No changes were sent to Mist.")
        sys.exit(0)

    # 3. Optional backup, then apply the change (portal-only PUT).
    backup_path = save_backup(ssid, wlan) if do_backup else None
    put_portal_password(cfg, wlan.get("portal") or {}, new_password)

    # 4. Mist accepted the PUT, so the new password may now be live. Publish
    #    it on stdout before anything else can fail.
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {kind[0].upper() + kind[1:]} for SSID '{ssid}' updated.")
    print(f"    New password: {new_password}", flush=True)

    # 5. Verify with a fresh GET. Do not trust the PUT echo.
    applied = (get_wlan(cfg).get("portal") or {}).get("password")
    if applied != new_password:
        _die(3, f"Mist accepted the update (submitted password "
                f"'{new_password}') but the password did not match on "
                f"read-back. Please verify in the Mist dashboard.")

    # 6. Record the new (shareable) password so staff can find it.
    try:
        record_new_password(ssid, new_password, cfg["wlan_id"], kind)
    except OSError as e:
        _die(1, f"Mist now uses password '{new_password}' for SSID '{ssid}', "
                f"but saving it locally failed: {e}")

    print(f"    Recorded in:  {CURRENT_PASSWORD_FILE.name} and {HISTORY_LOG.name}")
    if backup_path:
        print(f"    Backup saved: {backup_path.name}")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
        _die(3, str(e))
    except KeyboardInterrupt:
        _die(1, "Interrupted.")
