import mailbox

import bs4.builder
from bs4 import BeautifulSoup
import pandas as pd
import argparse
import logging

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

def get_email_text_content(mbox_mess):
    """
        Extract content from an mailbox message
    :param mbox_mess: mailbox message
    :return: text
    """
    content_type = mbox_mess.get_content_type()
    payload = mbox_mess.get_payload(decode=False)

    if isinstance(payload, list):
        for _mbox_part in payload:
            result = get_email_text_content(_mbox_part) # does depth first, if don't find a text, goes for next part
            if result is not None:
                return result
    elif content_type == 'text/plain':
        return payload
    elif content_type == 'text/html':
        try:
            return BeautifulSoup(payload, features="html.parser").get_text()
        except bs4.builder.ParserRejectedMarkup:
            return None
    else:
        return None

def remove_quoted_lines(text:str):
    """
    Remove lines that start with >
    """

    # Split the text into lines, and keep only lines that don't start with '>'
    lines = text.split('\n')
    lines = [line for line in lines if not line.startswith('>')]
    # Join the lines back into a single string
    return '\n'.join(lines)

def create_email_csv_dataset(mbox_filename:str, my_email_addresses:list, csv_file_output:str):
    """
    Create a CSV file with all emails composed by a list of email addresses from a mbox file

    :param mbox_filename: mbox filename
    :param my_email_addresses: list of email addresses
    :param csv_file_output: csv filename to output
    :return: None
    """


    logging.info(f"Reading mailbox: {mbox_filename}")
    mb = mailbox.mbox(mbox_filename)

    # index emails
    logging.info("Indexing emails")
    emails = {email.get('Message-ID'): email for email in mb}
    logging.info(f"Indexed {len(emails)} emails")

    logging.info("Creating dataframe")
    # Get a data frame out of it for faster processing
    emails_list = [dict(email.items()) for email in emails.values()] # This is only to get the total columns
    columns = pd.DataFrame(emails_list, dtype=str).columns

    # This needs to happen as somehow the items() list don't get all dict items
    emails_list = [{col: email.get(col) for col in columns} for email in emails.values()]

    df = pd.DataFrame(emails_list, dtype=str)
    df['Content-Type'] = df['Content-Type'].str.split(';', expand=True, n=1)[0].str.lower()  # loses charset info
    df.set_index('Message-ID', inplace=True)

    logging.info("Getting email content")
    email_text_content = {email.get('Message-ID'):get_email_text_content(email) for email in mb}

    logging.info("Getting replies")
    messages_replied = df[(~df['In-Reply-To'].isnull() & df['Subject'].str.upper().str.startswith('RE:'))]

    messages_i_replied = messages_replied[messages_replied['From'].str.contains('|'.join(my_email_addresses), regex=True, case=False)]

    messages_i_replied_tuple = [(replied_id, in_reply_to_id)
                                for (replied_id, in_reply_to_id) in list(messages_i_replied['In-Reply-To'].to_dict().items())
                                    if in_reply_to_id in email_text_content
                               ]

    logging.info(f"Dataset (total replies  {len(messages_i_replied_tuple)})")

    emails_replied = [dict(replied_id=replied_id,
                           reply_full_text=email_text_content[replied_id],
                           reply_no_quote=remove_quoted_lines(email_text_content[replied_id]),
                           mess_full=config.prompt_format.format(f_from=emails[replied_id].get('From',''),
                                                                 f_to=emails[replied_id].get('To',''),
                                                                 f_cc=emails[replied_id].get('Cc',''),
                                                                 f_subject=emails[replied_id].get('Subject',''),
                                                                 f_context=email_text_content[in_reply_to_id]))
                      for (replied_id, in_reply_to_id) in messages_i_replied_tuple
                      ]

    logging.info("Getting original emails sent")
    messages_i_started = df[(df['In-Reply-To'].isnull() & df['From'].str.contains('|'.join(my_email_addresses), regex=True, case=False))]
    logging.info(f"Dataset (total new emails  {len(messages_i_started)})")

    emails_i_started = [dict(replied_id=mess_id,
                           reply_full_text=email_text_content[mess_id],
                           reply_no_quote=email_text_content[mess_id],
                           mess_full=config.prompt_format.format(f_from=emails[mess_id].get('From',''),
                                                                 f_to=emails[mess_id].get('To',''),
                                                                 f_cc=emails[mess_id].get('Cc',''),
                                                                 f_subject=emails[mess_id].get('Subject',''),
                                                                 f_context=""))
                      for mess_id in messages_i_started.index
                      ]

    logging.info(f"Exporting {len(messages_i_started)+len(messages_i_replied_tuple)} emails to CSV: {csv_file_output}")
    df_emails = pd.DataFrame(emails_replied + emails_i_started)
    df_emails.to_csv(csv_file_output, index=False)



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Create email training set for LLMs.")
    parser.add_argument("-i", "--input", type=str, required=True, help="Mailbox file (.mbox)")
    parser.add_argument("-o", "--output", type=str, required=True, help="Output file (.csv)")
    parser.add_argument("-e", "--emails", required=True, nargs='+', help="List of senders emails (From)")

    args, unknown = parser.parse_known_args()

    create_email_csv_dataset(mbox_filename=args.input, my_email_addresses=args.emails, csv_file_output=args.output)

    # example run python .\convert_mbox_to_csv.py -i 'All mail Including Spam and Trash.mbox' -o "my_emails.csv" -e email@gmail.com email2@gmail.com email3@gmail.com