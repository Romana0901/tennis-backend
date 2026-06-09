from extensions import db


class Klijent(db.Model):
    __tablename__ = "klijenti"

    id = db.Column(db.Integer, primary_key=True)
    ime = db.Column(db.String(50), nullable=False)
    prezime = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(120), nullable=False, unique=True)
    telefon = db.Column(db.String(30), nullable=True)

    rezervacije = db.relationship("Rezervacija", backref="klijent", lazy=True)
    najmovi = db.relationship("NajamOpreme", backref="klijent", lazy=True)

    @property
    def ime_prezime(self):
        return f"{self.ime} {self.prezime}"

    def to_dict(self):
        return {
            "id": self.id,
            "ime": self.ime,
            "prezime": self.prezime,
            "email": self.email,
            "telefon": self.telefon,
            "ime_prezime": self.ime_prezime,
        }


class Teren(db.Model):
    __tablename__ = "tereni"

    id = db.Column(db.Integer, primary_key=True)
    naziv = db.Column(db.String(80), nullable=False)
    podloga = db.Column(db.String(40), nullable=False)
    lokacija = db.Column(db.String(100), nullable=False)
    cijena_po_satu = db.Column(db.Numeric(10, 2), nullable=False)
    aktivan = db.Column(db.Boolean, nullable=False, default=True)

    rezervacije = db.relationship("Rezervacija", backref="teren", lazy=True)

    def to_dict(self):
        return {
            "id": self.id,
            "naziv": self.naziv,
            "podloga": self.podloga,
            "lokacija": self.lokacija,
            "cijena_po_satu": float(self.cijena_po_satu),
            "aktivan": self.aktivan,
        }


class Oprema(db.Model):
    __tablename__ = "oprema"

    id = db.Column(db.Integer, primary_key=True)
    naziv = db.Column(db.String(80), nullable=False)
    kategorija = db.Column(db.String(50), nullable=False)
    ukupna_kolicina = db.Column(db.Integer, nullable=False)
    dostupna_kolicina = db.Column(db.Integer, nullable=False)
    cijena_najma = db.Column(db.Numeric(10, 2), nullable=False)

    najmovi = db.relationship("NajamOpreme", backref="oprema", lazy=True)

    def to_dict(self):
        return {
            "id": self.id,
            "naziv": self.naziv,
            "kategorija": self.kategorija,
            "ukupna_kolicina": self.ukupna_kolicina,
            "dostupna_kolicina": self.dostupna_kolicina,
            "cijena_najma": float(self.cijena_najma),
        }


class Rezervacija(db.Model):
    __tablename__ = "rezervacije"

    id = db.Column(db.Integer, primary_key=True)
    datum = db.Column(db.Date, nullable=False)
    vrijeme_pocetka = db.Column(db.Time, nullable=False)
    trajanje = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="Potvrđena")

    klijent_id = db.Column(db.Integer, db.ForeignKey("klijenti.id"), nullable=False)
    teren_id = db.Column(db.Integer, db.ForeignKey("tereni.id"), nullable=False)

    najmovi = db.relationship("NajamOpreme", backref="rezervacija", lazy=True)

    def to_dict(self):
        return {
            "id": self.id,
            "datum": self.datum.isoformat(),
            "vrijeme_pocetka": self.vrijeme_pocetka.strftime("%H:%M"),
            "trajanje": self.trajanje,
            "status": self.status,
            "klijent_id": self.klijent_id,
            "teren_id": self.teren_id,
            "klijent_ime_prezime": self.klijent.ime_prezime if self.klijent else "",
            "teren_naziv": self.teren.naziv if self.teren else "",
        }


class NajamOpreme(db.Model):
    __tablename__ = "najmovi_opreme"

    id = db.Column(db.Integer, primary_key=True)
    datum_najma = db.Column(db.Date, nullable=False)
    datum_povrata = db.Column(db.Date, nullable=True)
    kolicina = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="Aktivan")

    klijent_id = db.Column(db.Integer, db.ForeignKey("klijenti.id"), nullable=False)
    oprema_id = db.Column(db.Integer, db.ForeignKey("oprema.id"), nullable=False)
    rezervacija_id = db.Column(db.Integer, db.ForeignKey("rezervacije.id"), nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "datum_najma": self.datum_najma.isoformat(),
            "datum_povrata": self.datum_povrata.isoformat() if self.datum_povrata else "",
            "kolicina": self.kolicina,
            "status": self.status,
            "klijent_id": self.klijent_id,
            "oprema_id": self.oprema_id,
            "rezervacija_id": self.rezervacija_id,
            "klijent_ime_prezime": self.klijent.ime_prezime if self.klijent else "",
            "oprema_naziv": self.oprema.naziv if self.oprema else "",
            "rezervacija_opis": (
                f"{self.rezervacija.datum.isoformat()} - {self.rezervacija.teren.naziv}"
                if self.rezervacija and self.rezervacija.teren else ""
            ),
        }
