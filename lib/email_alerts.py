#!/usr/bin/env python
"""A simple wrapper to send email alerts."""



from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import re
import smtplib

from grr.lib import config_lib
from grr.lib import utils


def RemoveHtmlTags(data):
  p = re.compile(r"<.*?>")
  return p.sub("", data)


def SendEmail(to_addresses, from_address, subject, message, is_html=True):
  """This method sends an email notification."""

  if is_html:
    msg = MIMEMultipart("alternative")
    text = RemoveHtmlTags(message)
    part1 = MIMEText(text, "plain")
    part2 = MIMEText(message, "html")
    msg.attach(part1)
    msg.attach(part2)
  else:
    msg = MIMEText(message)

  msg["Subject"] = subject
  msg["From"] = from_address
  msg["To"] = to_addresses

  s = smtplib.SMTP(config_lib.CONFIG["Worker.smtp_server"],
                   int(config_lib.CONFIG["Worker.smtp_port"]))
  s.sendmail(from_address, [to_addresses], msg.as_string())
  s.quit()


