import psycopg2
from psycopg2 import sql
from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD

def get_db_connection(dbname=None):
    """
    Connect to a specific database. Defaults to DB_NAME from config.
    """
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=dbname or DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD
        )
        return conn
    except Exception as e:
        print(f"Error connecting to database '{dbname or DB_NAME}': {e}")
        return None

def init_db():
    """
    Initialize the database:
    1. Check if the database exists, create if not.
    2. Create the chat_history table if not exists.
    """
    print(f"Initializing database '{DB_NAME}'...")
    
    # Step 1: Create Database if it doesn't exist
    try:
        # Connect to default 'postgres' database to manage databases
        conn = get_db_connection(dbname='Yogateria')
        if conn:
            conn.autocommit = True
            cur = conn.cursor()
            
            # Check if database exists
            cur.execute("SELECT 1 FROM pg_catalog.pg_database WHERE datname = %s", (DB_NAME,))
            exists = cur.fetchone()
            
            if not exists:
                print(f"Database '{DB_NAME}' not found. Creating...")
                # Use psycopg2.sql to safely construct the CREATE DATABASE identifier
                cur.execute(sql.SQL("CREATE DATABASE {}").format(
                    sql.Identifier(DB_NAME))
                )
                print(f"Database '{DB_NAME}' created successfully.")
            else:
                print(f"Database '{DB_NAME}' already exists.")
            
            cur.close()
            conn.close()
    except Exception as e:
        print(f"Warning during database creation check: {e}")
        print("Will attempt to connect to target database directly...")

    # Step 2: Create Table inside the target database
    try:
        conn = get_db_connection()
        if conn:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS chat_history (
                    id SERIAL PRIMARY KEY,
                    user_message TEXT NOT NULL,
                    bot_response TEXT NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.commit()
            print("Table 'chat_history' checked/created successfully.")
            
            # Check if feedback column exists, if not add it
            cur.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='chat_history' AND column_name='feedback';
            """)
            if not cur.fetchone():
                print("Adding 'feedback' column to chat_history table...")
                cur.execute("ALTER TABLE chat_history ADD COLUMN feedback VARCHAR(10);")
                conn.commit()
            
            # Create good_feedback table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS good_feedback (
                    id SERIAL PRIMARY KEY,
                    chat_id INTEGER REFERENCES chat_history(id),
                    feedback_text TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            print("Table 'good_feedback' checked/created successfully.")

            # Create bad_feedback table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS bad_feedback (
                    id SERIAL PRIMARY KEY,
                    chat_id INTEGER REFERENCES chat_history(id),
                    feedback_text TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            print("Table 'bad_feedback' checked/created successfully.")
            
            conn.commit()
            
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id TEXT PRIMARY KEY,
                    gender TEXT,
                    size TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            print("Table 'user_profiles' checked/created successfully.")
            conn.commit()
            
            cur.close()
            conn.close()
        else:
            print("Failed to connect to target database to create table.")
    except Exception as e:
        print(f"Error initializing table: {e}")

def get_user_profile(user_id):
    try:
        conn = get_db_connection()
        if conn:
            cur = conn.cursor()
            cur.execute("SELECT gender, size FROM user_profiles WHERE user_id = %s", (user_id,))
            result = cur.fetchone()
            cur.close()
            conn.close()
            if result:
                return {"gender": result[0], "size": result[1]}
    except Exception as e:
        print(f"Error getting user profile: {e}")
    return None

def save_user_profile(user_id, gender, size):
    try:
        conn = get_db_connection()
        if conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO user_profiles (user_id, gender, size) 
                VALUES (%s, %s, %s) 
                ON CONFLICT (user_id) 
                DO UPDATE SET gender = EXCLUDED.gender, size = EXCLUDED.size
            """, (user_id, gender, size))
            conn.commit()
            cur.close()
            conn.close()
            return True
    except Exception as e:
        print(f"Error saving user profile: {e}")
        return False

def save_chat_message(user_message, bot_response):
    """
    Save a chat message pair to the database.
    Returns the ID of the inserted message.
    """
    chat_id = None
    try:
        conn = get_db_connection()
        if conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO chat_history (user_message, bot_response) VALUES (%s, %s) RETURNING id",
                (user_message, bot_response)
            )
            result = cur.fetchone()
            if result:
                chat_id = result[0]
            conn.commit()
            cur.close()
            conn.close()
            # print(f"Chat message saved to DB with ID: {chat_id}")
    except Exception as e:
        print(f"Error saving chat message to DB: {e}")
    return chat_id

def update_chat_feedback(message_id, feedback):
    """
    Update the feedback for a specific chat message.
    """
    try:
        conn = get_db_connection()
        if conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE chat_history SET feedback = %s WHERE id = %s",
                (feedback, message_id)
            )
            conn.commit()
            cur.close()
            conn.close()
            return True
    except Exception as e:
        print(f"Error updating feedback: {e}")
        return False

def save_good_feedback(chat_id, feedback_text=None):
    """
    Save good feedback to the good_feedback table.
    """
    try:
        conn = get_db_connection()
        if conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO good_feedback (chat_id, feedback_text) VALUES (%s, %s)",
                (chat_id, feedback_text)
            )
            conn.commit()
            cur.close()
            conn.close()
            return True
    except Exception as e:
        print(f"Error saving good feedback: {e}")
        return False

def save_bad_feedback(chat_id, feedback_text=None):
    """
    Save bad feedback to the bad_feedback table.
    """
    try:
        conn = get_db_connection()
        if conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO bad_feedback (chat_id, feedback_text) VALUES (%s, %s)",
                (chat_id, feedback_text)
            )
            conn.commit()
            cur.close()
            conn.close()
            return True
    except Exception as e:
        print(f"Error saving bad feedback: {e}")
        return False
