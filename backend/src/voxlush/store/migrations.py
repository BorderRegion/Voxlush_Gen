"""Additive migrations; old assets, briefs and request/billing history stay intact."""

import json


def migrate(db):
    migrate_v4(db)
    if db.execute("SELECT value FROM meta WHERE key='schema'").fetchone()[0] == '5':
        return
    from voxlush.themes.composition import eligible_composition
    db.execute('BEGIN IMMEDIATE')
    try:
        # Derived admission cache only; original status, manifest, fees and counters remain intact.
        db.execute('ALTER TABLE samples ADD COLUMN composition_eligible INTEGER NOT NULL DEFAULT 0')
        db.execute('ALTER TABLE composition_stats ADD COLUMN ineligible_archives INTEGER NOT NULL DEFAULT 0')
        cursor = ''
        while True:
            rows = db.execute('''SELECT s.sample_id,s.composition_mode,a.manifest_json FROM samples s
                JOIN assets a ON a.sample_id=s.sample_id AND a.revision=s.revision AND a.is_current=1
                WHERE s.composition_mode IS NOT NULL AND s.sample_id>? ORDER BY s.sample_id LIMIT 512''',(cursor,)).fetchall()
            if not rows:
                break
            for row in rows:
                context = json.loads(row['manifest_json']).get('composition',{})
                valid = context.get('requested_mode') == row['composition_mode'] and eligible_composition(context)
                db.execute('UPDATE samples SET composition_eligible=? WHERE sample_id=?',(int(valid),row['sample_id']))
            cursor = rows[-1]['sample_id']
        eligible = '({r}.composition_mode IS NULL OR {r}.composition_eligible=1)'
        outcome = {
            'accepted': "{r}.status='accepted' AND " + eligible,
            'provisional': "{r}.status='provisional_pass' AND " + eligible,
            'active': "{r}.status IN ('ready','running','deferred','awaiting_review')",
            'rejected': "{r}.status='rejected' AND COALESCE({r}.reason_code,'')!='duplicate'",
            'duplicate': "COALESCE({r}.reason_code,'')='duplicate'",
        }
        visual_pass = """COALESCE(json_extract({r}.review_json,'$.status')='pass' AND
            ({r}.composition_mode IS NULL OR
             (json_extract({r}.review_json,'$.context_assessment.observed_mode')={r}.composition_mode
              AND json_extract({r}.review_json,'$.context_assessment.meets_requested')=1
              AND json_extract({r}.review_json,'$.context_assessment.extraneous_environment')=0
              AND (json_extract({r}.review_json,'$.context_assessment.building_focus')='dominant'
                   OR ({r}.composition_mode IN ('contextual','environment_rich') AND
                       json_extract({r}.review_json,'$.context_assessment.building_focus')='co_primary')))),0)"""
        for table, prefix, keys, fields in (
            ('seed_stats','samples_stats',{'campaign_id':'{r}.campaign_id','family_id':'{r}.family_id','theme_seed_id':'{r}.theme_seed_id'},
             {**outcome,'planned':'1'}),
            ('composition_stats','composition',{'campaign_id':'{r}.campaign_id','scene_type':'{r}.scene_type','composition_mode':"COALESCE({r}.composition_mode,'')"},
             {**outcome,'tasks':'1','requests':'{r}.request_count',
              'visual_reviewed':"COALESCE(json_extract({r}.review_json,'$.status') IN ('pass','fail','gray'),0)",
              'visual_pass':visual_pass,
              'ineligible_archives':"{r}.status IN ('accepted','provisional_pass') AND NOT " + eligible}),
        ):
            for event in ('insert','update','delete'):
                db.execute(f'DROP TRIGGER {prefix}_{event}')
            db.execute(f'DELETE FROM {table}')
            columns = ','.join([*keys,*fields])
            key_values = ','.join(v.format(r='s') for v in keys.values())
            sums = ','.join(f'SUM({v.format(r="s")})' for v in fields.values())
            db.execute(f'INSERT INTO {table}({columns}) SELECT {key_values},{sums} FROM samples s GROUP BY {key_values}')

            def delta(row, sign):
                changes = ','.join(f'{k}={k}{sign}({v.format(r=row)})' for k,v in fields.items())
                where = ' AND '.join(f'{k}={v.format(r=row)}' for k,v in keys.items())
                return f'UPDATE {table} SET {changes} WHERE {where};'

            initialize = f"INSERT OR IGNORE INTO {table}({','.join(keys)}) VALUES({','.join(v.format(r='NEW') for v in keys.values())});"
            db.execute(f'CREATE TRIGGER {prefix}_insert AFTER INSERT ON samples BEGIN {initialize} {delta("NEW","+")} END')
            db.execute(f'''CREATE TRIGGER {prefix}_update AFTER UPDATE OF status,reason_code,request_count,review_json,campaign_id,family_id,theme_seed_id,scene_type,composition_mode,composition_eligible ON samples
                BEGIN {delta('OLD','-')} {initialize} {delta('NEW','+')} END''')
            db.execute(f'CREATE TRIGGER {prefix}_delete AFTER DELETE ON samples BEGIN {delta("OLD","-")} END')
        db.execute("UPDATE meta SET value='5' WHERE key='schema'")
        db.execute('COMMIT')
    except BaseException:
        db.execute('ROLLBACK')
        raise


def migrate_v4(db):
    migrate_v3(db)
    version = db.execute("SELECT value FROM meta WHERE key='schema'").fetchone()[0]
    if version in ('4','5'):
        return
    db.execute('BEGIN IMMEDIATE')
    try:
        # NULL preserves legacy intent: old samples are not retrospectively labelled.
        db.execute('ALTER TABLE campaigns ADD COLUMN composition_weights TEXT')
        db.execute('ALTER TABLE samples ADD COLUMN composition_mode TEXT')
        db.execute("ALTER TABLE exports ADD COLUMN composition_selection TEXT NOT NULL DEFAULT '{}'")
        db.execute('CREATE INDEX samples_composition ON samples(campaign_id,composition_mode,sample_id)')
        db.execute('''CREATE TABLE composition_stats (
            campaign_id TEXT NOT NULL,scene_type TEXT NOT NULL,composition_mode TEXT NOT NULL,
            tasks INTEGER NOT NULL DEFAULT 0,active INTEGER NOT NULL DEFAULT 0,
            accepted INTEGER NOT NULL DEFAULT 0,provisional INTEGER NOT NULL DEFAULT 0,
            rejected INTEGER NOT NULL DEFAULT 0,duplicate INTEGER NOT NULL DEFAULT 0,
            requests INTEGER NOT NULL DEFAULT 0,visual_reviewed INTEGER NOT NULL DEFAULT 0,
            visual_pass INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(campaign_id,scene_type,composition_mode))''')
        fields = {
            'tasks': '1', 'active': "{r}.status IN ('ready','running','deferred','awaiting_review')",
            'accepted': "{r}.status='accepted'", 'provisional': "{r}.status='provisional_pass'",
            'rejected': "{r}.status='rejected' AND COALESCE({r}.reason_code,'')!='duplicate'",
            'duplicate': "COALESCE({r}.reason_code,'')='duplicate'", 'requests': '{r}.request_count',
            'visual_reviewed': "COALESCE(json_extract({r}.review_json,'$.status') IN ('pass','fail','gray'),0)",
            'visual_pass': "COALESCE(json_extract({r}.review_json,'$.status')='pass',0)",
        }
        columns = ','.join(fields)
        sums = ','.join(f'SUM({condition.format(r="s")})' for condition in fields.values())
        db.execute(f'''INSERT INTO composition_stats(campaign_id,scene_type,composition_mode,{columns})
            SELECT campaign_id,scene_type,COALESCE(composition_mode,''),{sums} FROM samples s
            GROUP BY campaign_id,scene_type,composition_mode''')

        def delta(row, sign):
            assignments = ','.join(f'{name}={name}{sign}({condition.format(r=row)})' for name, condition in fields.items())
            return (f'UPDATE composition_stats SET {assignments} WHERE campaign_id={row}.campaign_id '
                    f"AND scene_type={row}.scene_type AND composition_mode=COALESCE({row}.composition_mode,'');")

        initialize = "INSERT OR IGNORE INTO composition_stats(campaign_id,scene_type,composition_mode) VALUES(NEW.campaign_id,NEW.scene_type,COALESCE(NEW.composition_mode,''));"
        db.execute(f'CREATE TRIGGER composition_insert AFTER INSERT ON samples BEGIN {initialize} {delta("NEW", "+")} END')
        db.execute(f'''CREATE TRIGGER composition_update AFTER UPDATE OF status,reason_code,request_count,review_json,campaign_id,scene_type,composition_mode ON samples
            BEGIN {delta('OLD','-')} {initialize} {delta('NEW','+')} END''')
        db.execute(f'CREATE TRIGGER composition_delete AFTER DELETE ON samples BEGIN {delta("OLD","-")} END')
        db.execute("UPDATE meta SET value='4' WHERE key='schema'")
        db.execute('COMMIT')
    except BaseException:
        db.execute('ROLLBACK')
        raise


def migrate_v3(db):
    migrate_v2(db)
    version = db.execute("SELECT value FROM meta WHERE key='schema'").fetchone()[0]
    if version in ("3", "4", "5"):
        return
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute("ALTER TABLE samples ADD COLUMN creative_phase TEXT NOT NULL DEFAULT 'final' CHECK(creative_phase IN ('skeleton','final'))")
        db.execute("ALTER TABLE samples ADD COLUMN local_retries INTEGER NOT NULL DEFAULT 0")
        db.execute("CREATE INDEX attempts_campaign_occupied ON attempts(campaign_id) WHERE occupancy=1")
        cursor = ''
        while True:
            rows = db.execute("SELECT sample_id,task_json,revision,stage,status FROM samples WHERE sample_id>? AND status NOT IN ('accepted','provisional_pass','rejected') ORDER BY sample_id LIMIT 512", (cursor,)).fetchall()
            if not rows:
                break
            for row in rows:
                if json.loads(row['task_json']).get('generation_mode') != 'two_stage':
                    continue
                refined = db.execute("SELECT 1 FROM attempts WHERE sample_id=? AND role='refine' LIMIT 1", (row['sample_id'],)).fetchone()
                if row['stage'] == 'refine' or refined:
                    continue
                db.execute("UPDATE samples SET creative_phase='skeleton' WHERE sample_id=?", (row['sample_id'],))
                # v2 inferred phase from revision. Ambiguous in-progress old
                # repairs need evidence review, never another paid POST.
                if row['revision'] > 1:
                    db.execute("UPDATE samples SET status='blocked',reason_code='phase_recovery_required',lease_token=NULL,lease_owner=NULL,lease_until=NULL WHERE sample_id=?", (row['sample_id'],))
            cursor = rows[-1]['sample_id']
        db.execute("UPDATE meta SET value='3' WHERE key='schema'")
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise


def migrate_v2(db):
    version = db.execute("SELECT value FROM meta WHERE key='schema'").fetchone()[0]
    if version in ("2", "3", "4", "5"):
        return
    if version != "1":
        raise RuntimeError("unsupported schema: migration required")
    db.execute("BEGIN IMMEDIATE")
    try:
        for table, columns in {
            "samples": ["review_format_retries INTEGER NOT NULL DEFAULT 0", "runtime_config_hash TEXT"],
            "campaigns": ["runtime_config_hash TEXT"],
            "attempts": ["capacity_group TEXT", "execution_deadline REAL", "execution_evidence TEXT",
                         "response_applied INTEGER NOT NULL DEFAULT 0", "runtime_config_hash TEXT"],
            "dedup_features": ["upright_hash TEXT"],
        }.items():
            for column in columns:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {column}")
        db.execute("UPDATE attempts SET capacity_group='legacy:' || endpoint_alias")
        db.execute("UPDATE attempts SET response_applied=1 WHERE NOT EXISTS (SELECT 1 FROM samples s WHERE s.attempt_id=attempts.attempt_id AND s.revision=attempts.revision AND s.stage=attempts.role)")
        db.executescript("""
        CREATE INDEX attempts_occupied ON attempts(capacity_group,campaign_id,status) WHERE occupancy=1;
        CREATE INDEX attempts_recent ON attempts(capacity_group,started_at,reserved_tokens);
        CREATE INDEX attempts_running ON attempts(campaign_id) WHERE status='running';
        CREATE INDEX attempts_pending_response ON attempts(sample_id,revision) WHERE response_applied=0;
        CREATE INDEX samples_pending ON samples(campaign_id,stage,updated_at,next_ready_at) WHERE status IN ('ready','deferred');
        CREATE INDEX samples_inflight ON samples(campaign_id,stage,status) WHERE status IN ('ready','running','deferred');
        CREATE INDEX samples_page ON samples(campaign_id,sample_id);
        CREATE INDEX assets_recent ON assets(campaign_id,created_at) WHERE accepted_unique=1;
        CREATE INDEX assets_lineage ON assets(lineage_group,is_current);
        CREATE INDEX dedup_upright ON dedup_features(upright_hash);
        CREATE TABLE family_health (
          campaign_id TEXT NOT NULL,family_id TEXT NOT NULL,failures INTEGER NOT NULL DEFAULT 0,
          last_failure_at REAL NOT NULL DEFAULT 0,PRIMARY KEY(campaign_id,family_id));
        CREATE TABLE config_snapshots (
          config_hash TEXT PRIMARY KEY,profile_hash TEXT NOT NULL,config_json TEXT NOT NULL,created_at REAL NOT NULL);
        CREATE TABLE config_history (
          campaign_id TEXT NOT NULL,revision INTEGER NOT NULL,config_hash TEXT NOT NULL,
          campaign_json TEXT NOT NULL,created_at REAL NOT NULL,PRIMARY KEY(campaign_id,revision));
        CREATE TABLE seed_stats (
          campaign_id TEXT NOT NULL,family_id TEXT NOT NULL,theme_seed_id TEXT NOT NULL,
          accepted INTEGER NOT NULL DEFAULT 0,active INTEGER NOT NULL DEFAULT 0,
          rejected INTEGER NOT NULL DEFAULT 0,duplicate INTEGER NOT NULL DEFAULT 0,
          provisional INTEGER NOT NULL DEFAULT 0,planned INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY(campaign_id,family_id,theme_seed_id));
        INSERT INTO seed_stats
          SELECT campaign_id,family_id,theme_seed_id,SUM(status='accepted'),
            SUM(status IN ('ready','running','deferred','awaiting_review')),
            SUM(status='rejected' AND COALESCE(reason_code,'')!='duplicate'),
            SUM(COALESCE(reason_code,'')='duplicate'),SUM(status='provisional_pass'),COUNT(*)
          FROM samples GROUP BY campaign_id,family_id,theme_seed_id;
        """)
        # Summary updates are in the same SQLite transaction as the source row.
        fields = {
            "accepted": "status='accepted'",
            "active": "status IN ('ready','running','deferred','awaiting_review')",
            "rejected": "status='rejected' AND COALESCE({r}.reason_code,'')!='duplicate'",
            "duplicate": "COALESCE({r}.reason_code,'')='duplicate'",
            "provisional": "status='provisional_pass'",
            "planned": "1",
        }

        def delta(row, sign):
            values = []
            for name, condition in fields.items():
                expression = condition.format(r=row)
                if condition.startswith("status"):
                    expression = row + "." + expression
                values.append(f"{name}={name}{sign}({expression})")
            return f"UPDATE seed_stats SET {','.join(values)} WHERE campaign_id={row}.campaign_id AND family_id={row}.family_id AND theme_seed_id={row}.theme_seed_id;"

        initialize = "INSERT OR IGNORE INTO seed_stats(campaign_id,family_id,theme_seed_id) VALUES(NEW.campaign_id,NEW.family_id,NEW.theme_seed_id);"
        db.executescript(f"""
        CREATE TRIGGER samples_stats_insert AFTER INSERT ON samples BEGIN {initialize} {delta('NEW','+')} END;
        CREATE TRIGGER samples_stats_update AFTER UPDATE OF status,reason_code,campaign_id,family_id,theme_seed_id ON samples
          BEGIN {delta('OLD','-')} {initialize} {delta('NEW','+')} END;
        CREATE TRIGGER samples_stats_delete AFTER DELETE ON samples BEGIN {delta('OLD','-')} END;
        UPDATE meta SET value='2' WHERE key='schema';
        """)
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise
