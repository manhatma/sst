import uuid

from dataclasses import dataclass


@dataclass
class Linkage:
    Name: str
    HeadAngle: float
    MaxFrontStroke: float
    MaxRearStroke: float
    MaxFrontTravel: float
    MaxRearTravel: float
    LeverageRatio: list[float]
    ShockWheelCoeffs: list[float]


@dataclass
class Calibration:
    Name: str
    MethodId: uuid.UUID
    Inputs: dict[str: float]

    def __post_init__(self):
        self.MethodId = uuid.UUID(self.MethodId)


@dataclass
class StrokeStat:
    SumTravel: float
    MaxTravel: float
    P95Travel: float
    SumVelocity: float
    MaxVelocity: float
    P95VelocityCompression: float
    P95VelocityRebound: float
    Bottomouts: int
    Count: int


@dataclass
class Stroke:
    Start: int
    End: int
    Stat: StrokeStat
    DigitizedTravel: list[int]
    DigitizedVelocity: list[int]
    FineDigitizedVelocity: list[int]


@dataclass
class Strokes:
    Compressions: list[Stroke]
    Rebounds: list[Stroke]

    def __post_init__(self):
        self.Compressions = [dataclass_from_dict(Stroke, d) for d in self.Compressions]
        self.Rebounds = [dataclass_from_dict(Stroke, d) for d in self.Rebounds]


@dataclass
class Airtime:
    Start: float
    End: float


@dataclass
class Suspension:
    Present: bool
    Calibration: Calibration
    Travel: list[float]
    Velocity: list[float]
    Strokes: Strokes
    TravelBins: list[float]
    VelocityBins: list[float]
    FineVelocityBins: list[float]
    GlobalMaxTravelAllData: float = 0.0 # Hinzugefügt für globale Statistiken
    GlobalP95TravelAllData: float = 0.0 # Hinzugefügt für globale Statistiken
    GlobalAvgTravelAllData: float = 0.0 # Hinzugefügt für globale Statistiken


@dataclass
class Telemetry:
    Name: str
    Version: int
    SampleRate: int
    Timestamp: int
    Front: Suspension
    Rear: Suspension
    Linkage: Linkage
    Airtimes: list[Airtime]

    def __post_init__(self):
        self.Airtimes = [dataclass_from_dict(Airtime, d) for d in self.Airtimes]


def _dfd(klass: type, d: dict):
    # source: https://stackoverflow.com/a/54769644
    try:
        annotations = klass.__annotations__
        # Bearbeite Felder, die Annotationen haben und im Dictionary vorhanden sind
        annotated_fields = {
            f: _dfd(annotations[f], d[f]) for f in annotations if f in d}
        # Felder, die im Dictionary sind, aber keine Annotationen haben (oder nicht im Konstruktor sind)
        # In Python 3.9+ könnten wir klass.__dataclass_fields__ verwenden, um nur Dataclass-Felder zu prüfen.
        # Hier wird angenommen, dass alle annotierten Felder im Konstruktor sind.
        # Die verbleibenden Felder im Dictionary, die nicht annotiert sind, werden direkt gesetzt.
        
        # Erstelle das Objekt mit den annotierten Feldern
        o = klass(**annotated_fields)

        # Setze alle Felder aus d, die nicht Teil der Konstruktorargumente (annotated_fields) waren
        # oder die keine Typ-Annotationen haben, aber in d vorhanden sind.
        # Dies ist nützlich, wenn d zusätzliche Felder enthält, die man trotzdem setzen möchte.
        all_init_fields = {f.name for f in getattr(klass, '__dataclass_fields__', {}).values() if f.init}
        
        for f_name in d:
            if f_name not in annotated_fields: # Nur wenn nicht schon im Konstruktor verwendet
                 # Prüfe, ob das Feld zur Klasse gehört (entweder annotiert oder nicht-init Dataclass-Feld)
                 # oder ob es einfach ein zusätzliches Attribut ist, das wir setzen wollen.
                 # Für Dataclasses ist es sicherer, nur definierte Felder zu setzen.
                 # Wenn es jedoch eine reguläre Klasse wäre, wäre setattr(o, f, d[f]) üblicher.
                 # Hier bleiben wir dabei, dass nur annotierte (und somit im Konstruktor berücksichtigte)
                 # oder explizit definierte (aber nicht-init) Felder sicher sind.
                 # Da wir hier `klass(**annotated_fields)` verwenden, ist es besser, hier keine weiteren Felder zu setzen,
                 # es sei denn, die Klasse ist so konzipiert, dass sie zusätzliche Attribute dynamisch aufnimmt.
                 # Für eine strikte Dataclass-Konvertierung sollten nur definierte Felder berücksichtigt werden.
                 # Die ursprüngliche Logik mit non_annotated_fields war etwas breiter.
                 # Wir bleiben bei der ursprünglichen Logik, um das Verhalten nicht zu ändern:
                 pass # Die ursprüngliche Logik mit `non_annotated_fields` wird unten beibehalten.


        # Die ursprüngliche Logik für non_annotated_fields:
        # Felder, die im Dictionary d sind, aber keine Annotationen in klass haben.
        non_annotated_in_dict = [f_key for f_key in d if f_key not in klass.__annotations__]
        for f_key in non_annotated_in_dict:
            # Prüfen, ob das Feld in der Klasse existiert (z.B. als Nicht-Init-Feld in einer Dataclass)
            # oder ob es ein neues Attribut sein soll.
            # Um sicherzustellen, dass wir keine beliebigen Attribute setzen, könnten wir hier prüfen,
            # ob f_key ein bekanntes Feld der Klasse ist.
            # Für die Flexibilität der ursprünglichen Logik:
            try:
                setattr(o, f_key, d[f_key])
            except AttributeError:
                 # Ignorieren, wenn das Attribut nicht gesetzt werden kann (z.B. bei Properties ohne Setter)
                 pass


        return o
    except Exception: # Geändert von BaseException zu Exception für typischere Fehlerbehandlung
        # Fallback für spezielle Typen wie uuid.UUID, wenn d direkt der Wert ist
        if isinstance(d, str) and klass is uuid.UUID:
            try:
                return uuid.UUID(d)
            except ValueError:
                return d # Wenn Umwandlung fehlschlägt, Originalwert zurückgeben
        return d  # Nicht als Dataclass-Feld oder spezieller Typ behandelt


def dataclass_from_dict(klass: type, d: dict):
    if not isinstance(d, dict): # Hinzugefügter Check
        return d # Wenn d kein Dictionary ist, kann es nicht konvertiert werden
    o = _dfd(klass, d)
    return o if isinstance(o, klass) else None