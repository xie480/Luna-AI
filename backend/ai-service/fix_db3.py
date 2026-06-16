import psycopg2

def main():
    conn = psycopg2.connect("dbname='luna' user='postgres' password='postgres' host='localhost' port='5432'")
    conn.autocommit = True
    cur = conn.cursor()
    
    print("Connected to DB.")
    # Try dropping as a constraint
    try:
        cur.execute('ALTER TABLE prompts DROP CONSTRAINT IF EXISTS idx_prompts_skill_phase_version CASCADE;')
        print("Successfully dropped constraint 'idx_prompts_skill_phase_version' (if it existed as constraint).")
    except Exception as e:
        print(f"Failed to drop constraint: {e}")
        
    # Try dropping as an index
    try:
        cur.execute('DROP INDEX IF EXISTS idx_prompts_skill_phase_version CASCADE;')
        print("Successfully dropped index 'idx_prompts_skill_phase_version' (if it existed as index).")
    except Exception as e:
        print(f"Failed to drop index: {e}")
        
    # See existing unique constraints
    cur.execute("""
        SELECT conname
        FROM pg_constraint
        WHERE conrelid = 'prompts'::regclass;
    """)
    result = cur.fetchall()
    print("Current constraints on 'prompts':", [r[0] for r in result])
    
    # See existing indices
    cur.execute("""
        SELECT indexname
        FROM pg_indexes
        WHERE tablename = 'prompts';
    """)
    result = cur.fetchall()
    print("Current indices on 'prompts':", [r[0] for r in result])
    
    cur.close()
    conn.close()

if __name__ == "__main__":
    main()
