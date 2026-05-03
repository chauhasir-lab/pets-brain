import schedule
import time
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_scanner():
    logger.info("PETS Scanner running...")

def main():
    logger.info("PETS Engine started.")
    schedule.every(1).minutes.do(run_scanner)
    
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    main()
