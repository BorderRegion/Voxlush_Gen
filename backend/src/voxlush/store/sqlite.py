"""Small DB-API facade over pinned APSW, which bundles WAL-reset-fixed SQLite."""
import apsw
sqlite_version = apsw.sqlitelibversion()
OperationalError = apsw.Error
IntegrityError = apsw.ConstraintError

class Row(dict):
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)

class Cursor:
    def __init__(self, cursor, row_factory):
        self.cursor = cursor
        self.row_factory = row_factory
        try:
            self.columns = [c[0] for c in cursor.get_description()]
        except apsw.ExecutionCompleteError:
            self.columns = []

    def fetchone(self):
        row = self.cursor.fetchone()
        return self.row_factory(zip(self.columns,row)) if row is not None and self.row_factory else row

    def fetchall(self):
        return list(self)

    def __iter__(self):
        while (row := self.fetchone()) is not None:
            yield row

class Connection:
    def __init__(self,path,**kwargs):
        self.raw = apsw.Connection(str(path))
        self.row_factory = None

    def execute(self,sql,parameters=()):
        return Cursor(self.raw.execute(sql,parameters),self.row_factory)

    def executemany(self,sql,parameters):
        return Cursor(self.raw.executemany(sql,parameters),self.row_factory)

    def executescript(self,sql):
        return self.execute(sql)

    def backup(self,target):
        with target.raw.backup("main",self.raw,"main") as backup:
            while not backup.done:
                backup.step(256)

    def close(self):
        self.raw.close()

connect = Connection
