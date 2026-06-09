from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import re

from flask import Flask, jsonify, request
from flask_cors import CORS
from sqlalchemy import and_, func, or_
from sqlalchemy.exc import IntegrityError

from extensions import db, migrate
from models import Klijent, NajamOpreme, Oprema, Rezervacija, Teren

app = Flask(__name__)
CORS(app)

app.config["SQLALCHEMY_DATABASE_URI"] = "mysql+pymysql://root:romana@localhost/tenis_rezervacije"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)
migrate.init_app(app, db)

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
REZERVACIJA_STATUSI = ["Potvrđena", "Otkazana", "Završena"]
NAJAM_STATUSI = ["Aktivan", "Vraćen", "Otkazan"]


def greska(poruka, status=400):
    return jsonify({"error": poruka}), status


def paginiraj(upit):
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 10, type=int)
    per_page = min(max(per_page, 1), 50)
    paginacija = upit.paginate(page=page, per_page=per_page, error_out=False)

    if page > paginacija.pages and paginacija.pages > 0:
        paginacija = upit.paginate(page=paginacija.pages, per_page=per_page, error_out=False)

    return jsonify({
        "items": [item.to_dict() for item in paginacija.items],
        "page": paginacija.page,
        "per_page": paginacija.per_page,
        "total": paginacija.total,
        "pages": paginacija.pages,
    })


def parse_date(vrijednost, naziv_polja, obavezno=True):
    if not vrijednost:
        if obavezno:
            raise ValueError(f"Polje {naziv_polja} je obavezno.")
        return None

    try:
        return datetime.strptime(vrijednost, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"Polje {naziv_polja} mora biti u formatu YYYY-MM-DD.")


def parse_time(vrijednost):
    if not vrijednost:
        raise ValueError("Vrijeme početka je obavezno.")

    try:
        vrijeme = datetime.strptime(vrijednost, "%H:%M").time()
    except ValueError:
        raise ValueError("Vrijeme početka mora biti u formatu HH:MM.")

    if vrijeme.minute != 0:
        raise ValueError("Vrijeme početka mora biti puni sat.")

    return vrijeme


def parse_positive_int(vrijednost, naziv_polja):
    try:
        broj = int(vrijednost)
    except (TypeError, ValueError):
        raise ValueError(f"Polje {naziv_polja} mora biti broj.")

    if broj <= 0:
        raise ValueError(f"Polje {naziv_polja} mora biti veće od 0.")

    return broj


def parse_hour_duration(vrijednost):
    trajanje = parse_positive_int(vrijednost, "trajanje")

    if trajanje % 60 != 0:
        raise ValueError("Trajanje mora biti u punim satima.")

    if trajanje > 300:
        raise ValueError("Rezervacija može trajati najviše 5 sati.")

    return trajanje


def parse_nonnegative_int(vrijednost, naziv_polja):
    try:
        broj = int(vrijednost)
    except (TypeError, ValueError):
        raise ValueError(f"Polje {naziv_polja} mora biti broj.")

    if broj < 0:
        raise ValueError(f"Polje {naziv_polja} ne može biti manje od 0.")

    return broj


def parse_positive_decimal(vrijednost, naziv_polja):
    try:
        broj = Decimal(str(vrijednost))
    except (InvalidOperation, TypeError):
        raise ValueError(f"Polje {naziv_polja} mora biti broj.")

    if broj <= 0:
        raise ValueError(f"Polje {naziv_polja} mora biti veće od 0.")

    return broj


def provjeri_obavezno(data, polja):
    for polje in polja:
        if data.get(polje) in [None, ""]:
            raise ValueError(f"Polje {polje} je obavezno.")


def vrijeme_kraj(rezervacija):
    pocetak = datetime.combine(rezervacija.datum, rezervacija.vrijeme_pocetka)
    return pocetak + timedelta(minutes=rezervacija.trajanje)


def termin_se_preklapa(teren_id, datum, vrijeme_pocetka, trajanje, rezervacija_id=None):
    novi_pocetak = datetime.combine(datum, vrijeme_pocetka)
    novi_kraj = novi_pocetak + timedelta(minutes=trajanje)

    upit = Rezervacija.query.filter(
        Rezervacija.teren_id == teren_id,
        Rezervacija.datum == datum,
        Rezervacija.status != "Otkazana",
    )

    if rezervacija_id:
        upit = upit.filter(Rezervacija.id != rezervacija_id)

    for rezervacija in upit.all():
        postojeci_pocetak = datetime.combine(rezervacija.datum, rezervacija.vrijeme_pocetka)
        postojeci_kraj = vrijeme_kraj(rezervacija)
        if novi_pocetak < postojeci_kraj and novi_kraj > postojeci_pocetak:
            return True

    return False


@app.route("/")
def index():
    return jsonify({"message": "Teniski centar API"})


@app.route("/dashboard")
def dashboard():
    danas = datetime.today().date()

    danasnje_rezervacije = Rezervacija.query.filter(
        Rezervacija.datum == danas,
        Rezervacija.status == "Potvrđena",
    ).order_by(Rezervacija.vrijeme_pocetka).limit(5).all()

    nadolazece_rezervacije = Rezervacija.query.filter(
        Rezervacija.datum >= danas,
        Rezervacija.status == "Potvrđena",
    ).order_by(Rezervacija.datum, Rezervacija.vrijeme_pocetka).limit(5).all()

    return jsonify({
        "broj_klijenata": Klijent.query.count(),
        "broj_terena": Teren.query.count(),
        "dostupna_oprema": int(db.session.query(func.coalesce(func.sum(Oprema.dostupna_kolicina), 0)).scalar() or 0),
        "buduce_rezervacije": Rezervacija.query.filter(
            Rezervacija.datum >= danas,
            Rezervacija.status == "Potvrđena",
        ).count(),
        "danasnje_rezervacije": [rezervacija.to_dict() for rezervacija in danasnje_rezervacije],
        "nadolazece_rezervacije": [rezervacija.to_dict() for rezervacija in nadolazece_rezervacije],
    })


@app.route("/klijenti", methods=["GET"])
def klijenti():
    q = request.args.get("q", "", type=str)
    upit = Klijent.query

    if q:
        pojam = f"%{q}%"
        upit = upit.filter(or_(
            Klijent.ime.ilike(pojam),
            Klijent.prezime.ilike(pojam),
            Klijent.email.ilike(pojam),
            Klijent.telefon.ilike(pojam),
        ))

    return paginiraj(upit.order_by(Klijent.id))


@app.route("/klijenti-dropdown")
def klijenti_dropdown():
    return jsonify([
        {"title": klijent.ime_prezime, "value": klijent.id}
        for klijent in Klijent.query.order_by(Klijent.prezime, Klijent.ime).all()
    ])


@app.route("/klijenti/<int:id>", methods=["GET"])
def klijent(id):
    zapis = Klijent.query.get_or_404(id)
    return jsonify(zapis.to_dict())


@app.route("/klijenti", methods=["POST"])
def novi_klijent():
    data = request.get_json() or {}

    try:
        provjeri_obavezno(data, ["ime", "prezime", "email"])
        if not EMAIL_REGEX.match(data.get("email")):
            return greska("Email nije ispravan.")

        zapis = Klijent(
            ime=data.get("ime"),
            prezime=data.get("prezime"),
            email=data.get("email"),
            telefon=data.get("telefon"),
        )
        db.session.add(zapis)
        db.session.commit()
        return jsonify(zapis.to_dict()), 201
    except ValueError as exc:
        return greska(str(exc))
    except IntegrityError:
        db.session.rollback()
        return greska("Klijent s ovom email adresom već postoji.")


@app.route("/klijenti/<int:id>", methods=["PUT"])
def uredi_klijenta(id):
    zapis = Klijent.query.get_or_404(id)
    data = request.get_json() or {}

    try:
        provjeri_obavezno(data, ["ime", "prezime", "email"])
        if not EMAIL_REGEX.match(data.get("email")):
            return greska("Email nije ispravan.")

        zapis.ime = data.get("ime")
        zapis.prezime = data.get("prezime")
        zapis.email = data.get("email")
        zapis.telefon = data.get("telefon")
        db.session.commit()
        return jsonify(zapis.to_dict())
    except ValueError as exc:
        return greska(str(exc))
    except IntegrityError:
        db.session.rollback()
        return greska("Klijent s ovom email adresom već postoji.")


@app.route("/klijenti/<int:id>", methods=["DELETE"])
def izbrisi_klijenta(id):
    zapis = Klijent.query.get_or_404(id)
    if zapis.rezervacije or zapis.najmovi:
        return greska("Klijent se ne može obrisati jer ima rezervacije ili najmove.", 409)

    db.session.delete(zapis)
    db.session.commit()
    return jsonify({"message": "Klijent je obrisan."})


@app.route("/tereni", methods=["GET"])
def tereni():
    q = request.args.get("q", "", type=str)
    aktivan = request.args.get("aktivan", "", type=str)
    upit = Teren.query

    if q:
        pojam = f"%{q}%"
        upit = upit.filter(or_(Teren.naziv.ilike(pojam), Teren.podloga.ilike(pojam), Teren.lokacija.ilike(pojam)))

    if aktivan in ["true", "false"]:
        upit = upit.filter(Teren.aktivan == (aktivan == "true"))

    return paginiraj(upit.order_by(Teren.id))


@app.route("/tereni-dropdown")
def tereni_dropdown():
    return jsonify([
        {"title": teren.naziv, "value": teren.id}
        for teren in Teren.query.filter_by(aktivan=True).order_by(Teren.naziv).all()
    ])


@app.route("/tereni/<int:id>", methods=["GET"])
def teren(id):
    zapis = Teren.query.get_or_404(id)
    return jsonify(zapis.to_dict())


@app.route("/tereni", methods=["POST"])
def novi_teren():
    data = request.get_json() or {}

    try:
        provjeri_obavezno(data, ["naziv", "podloga", "lokacija", "cijena_po_satu"])
        zapis = Teren(
            naziv=data.get("naziv"),
            podloga=data.get("podloga"),
            lokacija=data.get("lokacija"),
            cijena_po_satu=parse_positive_decimal(data.get("cijena_po_satu"), "cijena_po_satu"),
            aktivan=bool(data.get("aktivan", True)),
        )
        db.session.add(zapis)
        db.session.commit()
        return jsonify(zapis.to_dict()), 201
    except ValueError as exc:
        return greska(str(exc))


@app.route("/tereni/<int:id>", methods=["PUT"])
def uredi_teren(id):
    zapis = Teren.query.get_or_404(id)
    data = request.get_json() or {}

    try:
        provjeri_obavezno(data, ["naziv", "podloga", "lokacija", "cijena_po_satu"])
        zapis.naziv = data.get("naziv")
        zapis.podloga = data.get("podloga")
        zapis.lokacija = data.get("lokacija")
        zapis.cijena_po_satu = parse_positive_decimal(data.get("cijena_po_satu"), "cijena_po_satu")
        zapis.aktivan = bool(data.get("aktivan", True))
        db.session.commit()
        return jsonify(zapis.to_dict())
    except ValueError as exc:
        return greska(str(exc))


@app.route("/tereni/<int:id>", methods=["DELETE"])
def izbrisi_teren(id):
    zapis = Teren.query.get_or_404(id)
    if zapis.rezervacije:
        return greska("Teren se ne može obrisati jer ima rezervacije.", 409)

    db.session.delete(zapis)
    db.session.commit()
    return jsonify({"message": "Teren je obrisan."})


@app.route("/oprema", methods=["GET"])
def oprema():
    q = request.args.get("q", "", type=str)
    kategorija = request.args.get("kategorija", "", type=str)
    dostupno = request.args.get("dostupno", "", type=str)
    upit = Oprema.query

    if q:
        pojam = f"%{q}%"
        upit = upit.filter(or_(Oprema.naziv.ilike(pojam), Oprema.kategorija.ilike(pojam)))

    if kategorija:
        upit = upit.filter(Oprema.kategorija == kategorija)

    if dostupno == "true":
        upit = upit.filter(Oprema.dostupna_kolicina > 0)

    return paginiraj(upit.order_by(Oprema.id))


@app.route("/oprema-dropdown")
def oprema_dropdown():
    return jsonify([
        {"title": f"{item.naziv} ({item.dostupna_kolicina} dostupno)", "value": item.id}
        for item in Oprema.query.order_by(Oprema.naziv).all()
    ])


@app.route("/oprema/<int:id>", methods=["GET"])
def oprema_detalji(id):
    zapis = Oprema.query.get_or_404(id)
    return jsonify(zapis.to_dict())


@app.route("/oprema", methods=["POST"])
def nova_oprema():
    data = request.get_json() or {}

    try:
        provjeri_obavezno(data, ["naziv", "kategorija", "ukupna_kolicina", "dostupna_kolicina", "cijena_najma"])
        ukupno = parse_positive_int(data.get("ukupna_kolicina"), "ukupna_kolicina")
        dostupno = parse_nonnegative_int(data.get("dostupna_kolicina"), "dostupna_kolicina")
        if dostupno > ukupno:
            return greska("Dostupna količina ne može biti veća od ukupne količine.")

        zapis = Oprema(
            naziv=data.get("naziv"),
            kategorija=data.get("kategorija"),
            ukupna_kolicina=ukupno,
            dostupna_kolicina=dostupno,
            cijena_najma=parse_positive_decimal(data.get("cijena_najma"), "cijena_najma"),
        )
        db.session.add(zapis)
        db.session.commit()
        return jsonify(zapis.to_dict()), 201
    except ValueError as exc:
        return greska(str(exc))


@app.route("/oprema/<int:id>", methods=["PUT"])
def uredi_opremu(id):
    zapis = Oprema.query.get_or_404(id)
    data = request.get_json() or {}

    try:
        provjeri_obavezno(data, ["naziv", "kategorija", "ukupna_kolicina", "dostupna_kolicina", "cijena_najma"])
        ukupno = parse_positive_int(data.get("ukupna_kolicina"), "ukupna_kolicina")
        dostupno = parse_nonnegative_int(data.get("dostupna_kolicina"), "dostupna_kolicina")
        if dostupno > ukupno:
            return greska("Dostupna količina ne može biti veća od ukupne količine.")

        zapis.naziv = data.get("naziv")
        zapis.kategorija = data.get("kategorija")
        zapis.ukupna_kolicina = ukupno
        zapis.dostupna_kolicina = dostupno
        zapis.cijena_najma = parse_positive_decimal(data.get("cijena_najma"), "cijena_najma")
        db.session.commit()
        return jsonify(zapis.to_dict())
    except ValueError as exc:
        return greska(str(exc))


@app.route("/oprema/<int:id>", methods=["DELETE"])
def izbrisi_opremu(id):
    zapis = Oprema.query.get_or_404(id)
    if zapis.najmovi:
        return greska("Oprema se ne može obrisati jer postoje najmovi.", 409)

    db.session.delete(zapis)
    db.session.commit()
    return jsonify({"message": "Oprema je obrisana."})


@app.route("/rezervacije", methods=["GET"])
def rezervacije():
    q = request.args.get("q", "", type=str)
    datum = request.args.get("datum", "", type=str)
    status = request.args.get("status", "", type=str)
    teren_id = request.args.get("teren_id", "", type=str)
    upit = Rezervacija.query.join(Klijent).join(Teren)

    if q:
        pojam = f"%{q}%"
        upit = upit.filter(or_(
            Klijent.ime.ilike(pojam),
            Klijent.prezime.ilike(pojam),
            Teren.naziv.ilike(pojam),
            Rezervacija.status.ilike(pojam),
        ))

    if datum:
        try:
            upit = upit.filter(Rezervacija.datum == parse_date(datum, "datum"))
        except ValueError as exc:
            return greska(str(exc))

    if status:
        upit = upit.filter(Rezervacija.status == status)

    if teren_id:
        upit = upit.filter(Rezervacija.teren_id == int(teren_id))

    return paginiraj(upit.order_by(Rezervacija.datum.desc(), Rezervacija.vrijeme_pocetka))


@app.route("/rezervacije-dropdown")
def rezervacije_dropdown():
    klijent_id = request.args.get("klijent_id", "", type=str)
    upit = Rezervacija.query.filter(Rezervacija.status == "Potvrđena")

    if klijent_id:
        upit = upit.filter(Rezervacija.klijent_id == int(klijent_id))

    return jsonify([
        {
            "title": f"{rezervacija.datum.isoformat()} {rezervacija.vrijeme_pocetka.strftime('%H:%M')} - {rezervacija.teren.naziv}",
            "value": rezervacija.id,
        }
        for rezervacija in upit.order_by(Rezervacija.datum.desc(), Rezervacija.vrijeme_pocetka).all()
    ])


@app.route("/rezervacije/<int:id>", methods=["GET"])
def rezervacija(id):
    zapis = Rezervacija.query.get_or_404(id)
    return jsonify(zapis.to_dict())


@app.route("/rezervacije", methods=["POST"])
def nova_rezervacija():
    data = request.get_json() or {}

    try:
        provjeri_obavezno(data, ["datum", "vrijeme_pocetka", "trajanje", "status", "klijent_id", "teren_id"])
        datum = parse_date(data.get("datum"), "datum")
        vrijeme = parse_time(data.get("vrijeme_pocetka"))
        trajanje = parse_hour_duration(data.get("trajanje"))
        status = data.get("status")
        teren_id = int(data.get("teren_id"))

        if status not in REZERVACIJA_STATUSI:
            return greska("Status rezervacije nije ispravan.")

        if status != "Otkazana" and termin_se_preklapa(teren_id, datum, vrijeme, trajanje):
            return greska("Teren je zauzet u odabranom terminu.", 409)

        zapis = Rezervacija(
            datum=datum,
            vrijeme_pocetka=vrijeme,
            trajanje=trajanje,
            status=status,
            klijent_id=int(data.get("klijent_id")),
            teren_id=teren_id,
        )
        db.session.add(zapis)
        db.session.commit()
        return jsonify(zapis.to_dict()), 201
    except ValueError as exc:
        return greska(str(exc))


@app.route("/rezervacije/<int:id>", methods=["PUT"])
def uredi_rezervaciju(id):
    zapis = Rezervacija.query.get_or_404(id)
    data = request.get_json() or {}

    try:
        provjeri_obavezno(data, ["datum", "vrijeme_pocetka", "trajanje", "status", "klijent_id", "teren_id"])
        datum = parse_date(data.get("datum"), "datum")
        vrijeme = parse_time(data.get("vrijeme_pocetka"))
        trajanje = parse_hour_duration(data.get("trajanje"))
        status = data.get("status")
        teren_id = int(data.get("teren_id"))

        if status not in REZERVACIJA_STATUSI:
            return greska("Status rezervacije nije ispravan.")

        if status != "Otkazana" and termin_se_preklapa(teren_id, datum, vrijeme, trajanje, zapis.id):
            return greska("Teren je zauzet u odabranom terminu.", 409)

        zapis.datum = datum
        zapis.vrijeme_pocetka = vrijeme
        zapis.trajanje = trajanje
        zapis.status = status
        zapis.klijent_id = int(data.get("klijent_id"))
        zapis.teren_id = teren_id
        db.session.commit()
        return jsonify(zapis.to_dict())
    except ValueError as exc:
        return greska(str(exc))


@app.route("/rezervacije/<int:id>", methods=["DELETE"])
def izbrisi_rezervaciju(id):
    zapis = Rezervacija.query.get_or_404(id)
    if zapis.najmovi:
        return greska("Rezervacija se ne može obrisati jer ima povezane najmove opreme.", 409)

    db.session.delete(zapis)
    db.session.commit()
    return jsonify({"message": "Rezervacija je obrisana."})


def promijeni_stanje_opreme(najam, novi_status, nova_kolicina=None):
    stara_aktivna = najam.status == "Aktivan"
    nova_aktivna = novi_status == "Aktivan"
    kolicina = nova_kolicina if nova_kolicina is not None else najam.kolicina

    if stara_aktivna and not nova_aktivna:
        najam.oprema.dostupna_kolicina += najam.kolicina
    elif not stara_aktivna and nova_aktivna:
        if najam.oprema.dostupna_kolicina < kolicina:
            raise ValueError("Nema dovoljno dostupne opreme za najam.")
        najam.oprema.dostupna_kolicina -= kolicina
    elif stara_aktivna and nova_aktivna:
        razlika = kolicina - najam.kolicina
        if razlika > najam.oprema.dostupna_kolicina:
            raise ValueError("Nema dovoljno dostupne opreme za najam.")
        najam.oprema.dostupna_kolicina -= razlika


def provjeri_rezervaciju_najma(data):
    klijent_id = int(data.get("klijent_id"))
    rezervacija = Rezervacija.query.get_or_404(int(data.get("rezervacija_id")))

    if rezervacija.klijent_id != klijent_id:
        raise ValueError("Rezervacija ne pripada odabranom klijentu.")

    return klijent_id, rezervacija


@app.route("/najmovi-opreme", methods=["GET"])
def najmovi_opreme():
    q = request.args.get("q", "", type=str)
    status = request.args.get("status", "", type=str)
    klijent_id = request.args.get("klijent_id", "", type=str)
    upit = NajamOpreme.query.join(Klijent).join(Oprema)

    if q:
        pojam = f"%{q}%"
        upit = upit.filter(or_(Klijent.ime.ilike(pojam), Klijent.prezime.ilike(pojam), Oprema.naziv.ilike(pojam)))

    if status:
        upit = upit.filter(NajamOpreme.status == status)

    if klijent_id:
        upit = upit.filter(NajamOpreme.klijent_id == int(klijent_id))

    return paginiraj(upit.order_by(NajamOpreme.datum_najma.desc(), NajamOpreme.id.desc()))


@app.route("/najmovi-opreme/<int:id>", methods=["GET"])
def najam_opreme(id):
    zapis = NajamOpreme.query.get_or_404(id)
    return jsonify(zapis.to_dict())


@app.route("/najmovi-opreme", methods=["POST"])
def novi_najam_opreme():
    data = request.get_json() or {}

    try:
        provjeri_obavezno(data, ["datum_najma", "kolicina", "status", "klijent_id", "oprema_id", "rezervacija_id"])
        status = data.get("status")
        if status not in NAJAM_STATUSI:
            return greska("Status najma nije ispravan.")

        oprema = Oprema.query.get_or_404(int(data.get("oprema_id")))
        kolicina = parse_positive_int(data.get("kolicina"), "kolicina")
        klijent_id, rezervacija = provjeri_rezervaciju_najma(data)
        if status == "Aktivan" and oprema.dostupna_kolicina < kolicina:
            return greska("Nema dovoljno dostupne opreme za najam.", 409)

        zapis = NajamOpreme(
            datum_najma=parse_date(data.get("datum_najma"), "datum_najma"),
            datum_povrata=parse_date(data.get("datum_povrata"), "datum_povrata", False),
            kolicina=kolicina,
            status=status,
            klijent_id=klijent_id,
            oprema_id=oprema.id,
            rezervacija_id=rezervacija.id,
        )
        if status == "Aktivan":
            oprema.dostupna_kolicina -= kolicina

        db.session.add(zapis)
        db.session.commit()
        return jsonify(zapis.to_dict()), 201
    except ValueError as exc:
        return greska(str(exc))


@app.route("/najmovi-opreme/<int:id>", methods=["PUT"])
def uredi_najam_opreme(id):
    zapis = NajamOpreme.query.get_or_404(id)
    data = request.get_json() or {}

    try:
        provjeri_obavezno(data, ["datum_najma", "kolicina", "status", "klijent_id", "oprema_id", "rezervacija_id"])
        status = data.get("status")
        if status not in NAJAM_STATUSI:
            return greska("Status najma nije ispravan.")

        nova_oprema_id = int(data.get("oprema_id"))
        kolicina = parse_positive_int(data.get("kolicina"), "kolicina")
        nova_oprema = Oprema.query.get_or_404(nova_oprema_id)
        klijent_id, rezervacija = provjeri_rezervaciju_najma(data)

        if zapis.status == "Aktivan":
            zapis.oprema.dostupna_kolicina += zapis.kolicina

        if status == "Aktivan":
            if nova_oprema.dostupna_kolicina < kolicina:
                raise ValueError("Nema dovoljno dostupne opreme za najam.")
            nova_oprema.dostupna_kolicina -= kolicina

        zapis.datum_najma = parse_date(data.get("datum_najma"), "datum_najma")
        zapis.datum_povrata = parse_date(data.get("datum_povrata"), "datum_povrata", False)
        zapis.kolicina = kolicina
        zapis.status = status
        zapis.klijent_id = klijent_id
        zapis.oprema_id = nova_oprema_id
        zapis.rezervacija_id = rezervacija.id
        db.session.commit()
        return jsonify(zapis.to_dict())
    except ValueError as exc:
        db.session.rollback()
        return greska(str(exc))


@app.route("/najmovi-opreme/<int:id>", methods=["DELETE"])
def izbrisi_najam_opreme(id):
    zapis = NajamOpreme.query.get_or_404(id)
    if zapis.status == "Aktivan":
        zapis.oprema.dostupna_kolicina += zapis.kolicina

    db.session.delete(zapis)
    db.session.commit()
    return jsonify({"message": "Najam opreme je obrisan."})


if __name__ == "__main__":
    app.run(debug=True, port=5005)
