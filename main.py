import schedule
import time
import logging
from database import create_tables
from scanner import run_scanner, send_test_alert

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    logger.info("PETS Engine started.")
    create_tables()
    send_test_alert()
    schedule.every(1).minutes.do(run_scanner)
    
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    main()
