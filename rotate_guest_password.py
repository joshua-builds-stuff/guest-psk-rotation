#!/usr/bin/env python3
"""
Rotate Guest WiFi Password (Juniper Mist)
=========================================

Unattended rotation of a Mist guest captive-portal password.

Reads the WLAN selected during setup (see setup_guest_wlan.py) from
`.env`, pulls that WLAN's current JSON, and replaces the guest
portal password with a single randomly chosen, school-safe English word
(e.g. "apples", "rainbow", "penguin"). It then PUTs the full object back.

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
  2  validation error (WLAN is not a guest 'password' portal)
  3  Mist API / network error
"""

import argparse
import json
import secrets
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

API_TIMEOUT = 30  # seconds

# Allowlisted Mist cloud API hostnames (SSRF guard). Mirrors the 12 regional
# clouds published in the Mist OpenAPI spec / your standard env_handler.
_ALLOWED_HOSTS = frozenset({
    "api.mist.com", "api.gc1.mist.com", "api.ac2.mist.com", "api.gc2.mist.com",
    "api.gc4.mist.com", "api.eu.mist.com", "api.gc3.mist.com", "api.ac6.mist.com",
    "api.gc6.mist.com", "api.ac5.mist.com", "api.gc5.mist.com", "api.gc7.mist.com",
})

# Server-managed / immutable fields that should not be sent back on PUT.
_READONLY_WLAN_FIELDS = ("id", "org_id", "site_id", "created_time",
                         "modified_time", "for_site", "msp_id")

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
            parsed = json.loads(raw) if raw else None
            return resp.getcode(), parsed
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            detail = json.loads(raw)
        except Exception:
            detail = raw.decode("utf-8", errors="replace")[:500]
        return e.code, detail
    except urllib.error.URLError as e:
        raise RuntimeError(f"Connection error reaching Mist API: {e.reason}")


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


def put_wlan(cfg: dict, wlan_obj: dict) -> dict:
    """PUT the full WLAN object back. Exits on API error."""
    payload = {k: v for k, v in wlan_obj.items() if k not in _READONLY_WLAN_FIELDS}
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

def validate_guest_portal(wlan_obj: dict) -> None:
    """Ensure this WLAN is a guest 'password' captive portal, else exit."""
    portal = wlan_obj.get("portal") or {}
    auth = portal.get("auth")
    if auth != "password":
        _die(2, f"This is NOT a guest portal SSID: portal.auth is "
                f"{auth!r}, expected 'password'. Aborting; nothing changed.")


def generate_password() -> str:
    """Return one random, school-safe, memorable English word."""
    return secrets.choice(_WORDS)


def record_new_password(ssid: str, password: str) -> None:
    """Persist the new (shareable) password to local files for staff."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(HISTORY_LOG, "a", encoding="utf-8") as f:
        f.write(f"{timestamp}\t{ssid}\t{password}\n")
    with open(CURRENT_PASSWORD_FILE, "w", encoding="utf-8") as f:
        f.write(password + "\n")


def save_backup(ssid: str, wlan_obj: dict) -> Path:
    """Save a timestamped backup of the pre-change WLAN JSON."""
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_ssid = "".join(c if c.isalnum() else "_" for c in (ssid or "wlan"))
    path = BACKUP_DIR / f"{safe_ssid}_{stamp}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(wlan_obj, f, indent=2)
    return path


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

    # 1. Pull current WLAN JSON.
    wlan = get_wlan(cfg)
    ssid = wlan.get("ssid") or cfg["ssid"] or cfg["wlan_id"]

    # 2. Safety guard: must be a guest 'password' portal.
    validate_guest_portal(wlan)

    old_password = (wlan.get("portal") or {}).get("password")
    new_password = generate_password()
    # Avoid handing out the same word twice in a row.
    while new_password == old_password:
        new_password = generate_password()

    if args.dry_run:
        print(f"[DRY RUN] SSID '{ssid}': would set new guest password -> {new_password}")
        print("[DRY RUN] No changes were sent to Mist.")
        sys.exit(0)

    # 3. Optional backup, then apply the change (full-object PUT preserves all fields).
    backup_path = save_backup(ssid, wlan) if do_backup else None
    wlan.setdefault("portal", {})["password"] = new_password
    updated = put_wlan(cfg, wlan)

    # 4. Verify the change actually took effect.
    applied = (updated.get("portal") or {}).get("password")
    if applied != new_password:
        _die(3, "Mist accepted the update but the password did not match on "
                "read-back. Please verify in the Mist dashboard.")

    # 5. Record the new (shareable) password so staff can find it.
    record_new_password(ssid, new_password)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] Guest WiFi password for SSID '{ssid}' updated.")
    print(f"    New password: {new_password}")
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
