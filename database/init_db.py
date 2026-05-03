"""
Initialize SQLite database for tracking user activities
"""

import sqlite3
import os


def init_database():
    """Create the tracking database and tables"""
    db_path = os.path.join("data", "output", "tracking.db")

    # Create output directory if it doesn't exist
    os.makedirs(os.path.join("data", "output"), exist_ok=True)

    # Connect to database (creates file if it doesn't exist)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create search_logs table
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS search_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            search_query TEXT NOT NULL,
            filters_used TEXT,
            num_results INTEGER,
            user_session TEXT
        )
    """
    )

    # Create compare_view_logs table
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS compare_view_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            paper_ids TEXT NOT NULL,
            num_papers INTEGER,
            user_session TEXT
        )
    """
    )

    # Create download_logs table
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS download_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            paper_ids TEXT NOT NULL,
            num_papers INTEGER,
            file_format TEXT DEFAULT 'CSV',
            user_session TEXT
        )
    """
    )

    # Create upload_requests table
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS upload_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            request_name TEXT NOT NULL,
            institution TEXT NOT NULL,
            email TEXT NOT NULL,
            paper_info TEXT NOT NULL,
            change_requests TEXT,
            pdf_filename TEXT,
            status TEXT DEFAULT 'pending'
        )
    """
    )

    # Commit changes and close connection
    conn.commit()
    conn.close()

    print(f"Database initialized successfully at {db_path}")
    print("Created tables:")
    print("  - search_logs")
    print("  - compare_view_logs")
    print("  - download_logs")
    print("  - upload_requests")


if __name__ == "__main__":
    init_database()
