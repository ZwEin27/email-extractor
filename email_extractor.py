import re
import json
from sets import Set

class EE(object):
    """Extractor of email addresses from text.
    The legal definition is in https://en.wikipedia.org/wiki/Email_address

    This class attempts to map purposefully obfuscated email addresses to legal addresses.

    Users of this class should call EE.extract_email(), see documentation.
    The main program is to test against the ground truth.
    """

    EE_OUTPUT_FORMAT_LIST = 'list'
    EE_OUTPUT_FORMAT_OBFUSCATION = 'obfuscation'

    def __init__(self, _output_format='list'):

        self.common_domains = [
            "gmail",
            "gee mail",
            "g mail",
            "gml",
            "yahoo",
            "hotmail"
        ]
        self.common_domains_regex = "(?:" + "|".join(self.common_domains) + ")"

        self.gmail_synonyms = [
            "gee mail",
            "g mail"
            "gml"
        ]
        self.gmail_synonyms_regex = "(?:" + "|".join(self.gmail_synonyms) + ")"

        self.com_synonyms = [
            r"com\b",
            r"co\s*\.\s*\w\w\w?",
            r"co\s+dot\s+\w\w\w?"
        ]
        self.com_synonyms_regex = r"(?:" + "|".join(self.com_synonyms) + ")"

        # The intent here is to match things like "yahoo com", "yahoo dot com"
        # We require matching the com synonyms to avoid interpreting text that contains "at yahoo" as part of a domain name.
        self.spelled_out_domain_regex = r"(?:" + self.common_domains_regex + "(?:(?:dot\s+|\.+|\,+|\s+)" + self.com_synonyms_regex + "))"
        # print "spelled_out_domain_regex:%s" % spelled_out_domain_regex

        self.at_regexes = [
            r"@",
            r"\(+@\)+",
            r"\[+@\]+",
            r"\(+(?:at|arroba)\)+",
            r"\[+(?:at|arroba)\]+",
            r"\{+(?:at|arroba)\}+",
            r"\s+(?:at|arroba)@",
            r"@at\s+",
            r"at\s+(?=" + self.spelled_out_domain_regex + ")",
            r"(?<=\w\w\w|\wat)\s+(?=" + self.spelled_out_domain_regex + ")",
            r"(?<=\w\w\w|\wat)\[\](?=" + self.spelled_out_domain_regex + "?" + ")"
        ]
        self.at_regex = "(?:" + r'|'.join(self.at_regexes) + ")"
        # print "at_regex:%s" % at_regex

        # People put junk between the "at" sign and the start of the domain
        self.at_postfix_regexes = [
            ",+\s*",
            "\.+\s*"
        ]
        self.at_postfix_regex = "(?:" + r'|'.join(self.at_postfix_regexes) + ")?"

        self.full_at_regex = self.at_regex + self.at_postfix_regex + "\s*"
        # print "full_at_regex:%s" % full_at_regex

        # Character set defined by the standard
        self.basic_dns_label_regex = r"[a-zA-Z0-9][a-zA-Z0-9\-]*[a-zA-Z0-9]"
        self.non_dns_regex = r"[^a-zA-Z0-9\-.]"

        # Sometimes people do things like maria at (yahoo) (dot) (com)
        self.wrapped_basic_dns_label_regexes = [
            self.basic_dns_label_regex,
            "\(+" + self.basic_dns_label_regex + "\)+",
            "\[+" + self.basic_dns_label_regex + "\]+"
        ]
        self.dns_label_regex = "(?:" + "|".join(self.wrapped_basic_dns_label_regexes) + ")"

        # People put all kinds of junk between the parts of a domain name
        self.dot_regex = "[(\[]*dot[)\]]*"
        self.dns_separator_regexes = [
            "\s*\.+\s*",
            "[\.\s]+" + self.dot_regex + "[\.\s]+",
            "\(+(?:\.|" + self.dot_regex + ")+\)+",
            "\[+\.+\]+",
            "\{+\.+\}+",
            "\s+(?=" + self.com_synonyms_regex + ")"
        ]
        self.dns_separator_regex = "(?:" + ",*" + "|".join(self.dns_separator_regexes) + ",*" + ")"

        self.dns_re = self.full_at_regex + r"(" + self.dns_label_regex + r"(?:" + self.dns_separator_regex + self.dns_label_regex + r")*)"

        #
        # Regex for the user name part of legal addresses.
        # Assuming all text has been lowercased before.
        #
        # Assuming that special characters are not used, this can be added later.
        # from wikipedia: space and "(),:;<>@[\] characters are allowed with restrictions
        # all allowed: !#$%&'*+-/=?^_`{|}~ and space
        # allowed without quoting: !#$%&'*+-/?^_`{|}~, dot can appear, but not at the beginning

        # The full set requires starting with alphanumeric, this is because of all the junk
        # that appears often. Also require at least 4 characters.
        # full_username_regex = r"[a-z0-9][a-z0-9.!#$%&'*+-/?^_`{|}~]{3,}"
        self.full_username_regex = r"[a-z0-9]+(?:[-.!#$%&'*+/?^_`{|}~][a-z0-9]+)*"

        # The basic regex is for cases when there is no @ sign, which means there was plenty
        # of obfuscation and the potential for all kinds of decoration which we don't want in
        # the email address. We don't allow consecutive punctuation to avoid grabbing emails
        # such as me.......LouiseHolland41@gmail
        self.basic_username_regex = r"(?:[a-z0-9]+(?:(?:[-+_.]|[(]?dot[)]?)[a-z0-9]+)*\s*)"

        # use lookahead to find the @ immediately following the user name, with possible spaces.
        self.strict_username_regex = r"(?:" + self.full_username_regex + r"(?=@))"

        self.username_regex = r"(" + self.basic_username_regex + r"|" + self.strict_username_regex + r")"

        self.email_regex = self.username_regex + self.dns_re
        self.set_output_format(_output_format)


    def set_output_format(self, _output_format):
        # 1. list, 2. obfuscation
        if _output_format not in [EE.EE_OUTPUT_FORMAT_LIST, EE.EE_OUTPUT_FORMAT_OBFUSCATION]:
            raise Exception('output_format should be "list" or "obfuscation"')
        self.output_format = _output_format

    def clean_domain(self, regex_match):
        """Once we compute the domain, santity check it, being conservative and throwing out
        suspicious domains. Prefer precision to recall.

        :param regex_match: the output of our regex matching
        :type regex_match: string
        :return:
        :rtype:
        """
        # print "clean_domain:%s" % regex_match
        result = regex_match
        result = re.sub(self.gmail_synonyms_regex, "gmail", result)
        result = re.sub("\s+", ".", result)
        result = re.sub(self.dot_regex, ".", result)
        result = re.sub(self.non_dns_regex, "", result)
        result = re.sub("\.+", ".", result)
        result = result.strip()

        # If the domain ends with one of the common domains, add .com at the end
        if re.match(self.common_domains_regex + "$", result):
            result += ".com"
        # All domains have to contain a .
        if result.find('.') < 0:
            return ''
        # If the doman contains gmail, it has has to be gmail.com
        # This is drastic because of examples such as "at faithlynn1959@gmail. in call"
        if result.find('gmail') >= 0:
            if result != 'gmail.com':
                return ''
        return result

    @staticmethod
    def clean_username(string):
        """

        :param string:
        :type string:
        :return:
        :rtype:
        """
        username = string.strip()
        username = re.sub("[(]?dot[)]?", '.', username)
        # paranoid sanity check to reject short user names.
        if len(username) < 4:
            return None
        return username

    def clean(self, matches):
        clean_results = Set()
        for (u, d) in matches:
            # print "user: %s, domain: %s" % (u, d)
            domain = self.clean_domain(d)
            username = EE.clean_username(u)
            if domain and username:
                email = username + "@" + domain
                clean_results.add(email)
                # print ">>> %s" % email
        return list(clean_results)

    def extract_domain(self, string):
        """Extract the domain part of an email address within a string.
        Separate method used for testing purposes only.
        :param string:
        :return:
        :rtype:
        """
        matches = re.findall(self.dns_re, string, re.I)

        clean_results = []
        for m in matches:
            clean_results.append(self.clean_domain(m))
            # print("domains: "+', '.join(clean_results))
        # print "\n"
        return clean_results

    def normalize(self, clean, unclean, output_format):
        if self.output_format == EE.EE_OUTPUT_FORMAT_LIST:
            return clean
        else:
            output = []
            for co in clean:
                email = {}
                email['email'] = co
                tmp_unclean = list(unclean)
                # print co, tmp_unclean
                if co in [username.strip() + "@" + domain.strip() for username, domain in tmp_unclean if domain and username]:
                    # print co
                    for tuc in tmp_unclean:
                        username, domain = tuc
                        tuc_string = username.strip() + "@" + domain.strip()
                        if tuc_string == co:
                            unclean.remove(tuc)
                            continue
                        domain = self.clean_domain(domain)
                        username = EE.clean_username(username)
                        if domain and username:
                            email_string = username + "@" + domain
                            if email_string == co:
                                email['obfuscation'] = 'True'
                    if 'obfuscation' not in email:
                        email['obfuscation'] = 'False'
                else:
                    email['obfuscation'] = 'True'
                output.append(email)
            return output









            # uc_tc = self.clean(unclean)
            # for co in clean:
            #     email = {}
            #     email['email'] = co
            #     if co in unclean:
            #         for uo in uc_tc:
            #             if co == uo:
            #                 email['obfuscation'] = 'True'
            #                 break
            #         if obfuscation not in email:
            #             email['obfuscation'] = 'False'
            #     else:
            #         email['obfuscation'] = 'True'
            #     output.append(email)
            return output

    def extract_email(self, string, return_as_string=False):
        """Extract email address from string.
        :param string: the text to extract from
        :param return_as_string: whether to return the result as a string of comma-separated values or
        as a set
        :type return_as_string: Boolean
        """
        line = string.lower().replace('\n', ' ').replace('\r', '')
        line = re.sub(r"[*?]+", " ", line)
        line = re.sub(r"\\n", " ", line)
        line = re.sub(r"\s+g\s+mail\s+", " gmail ", line)
        # print line
        # return EE.extract_domain(line)

        matches = re.findall(self.email_regex, line)
        clean_results = self.clean(matches)
        # matches = [username.strip() + "@" + domain.strip() for username, domain in matches if domain and username]
        # print '#'*20
        # print [username.strip() + "@" + domain.strip() for username, domain in matches if domain and username]
        # print clean_results
        output = self.normalize(clean_results, matches, self.output_format)
        
        if return_as_string:
            return ",".join(output)
        else:
            return output


if __name__ == '__main__':
    text = 'Hey, \n \nWant some of this G-mail details  \nmarycomeaux62(@)gmail(dot)com\n'
    text = 'HOTMAIL:  sebasccelis@hotmail.com'
    print EE(_output_format='obfuscation').extract_email(text)
    # path = 'emails_ground_truth_obfuscation.json'
    # with open(path) as gt_file:
    #     ground_truth = json.load(gt_file)

    #     correct = 0
    #     incorrect = 0
    #     not_recalled = 0
    #     incorrectly_extracted = []
    #     not_extracted = []
    #     for r in ground_truth:
    #         found = False
    #         sentence = r["sentence"]
    #         # print "as string: %s" % EE.extract_email(sentence, True)
    #         emails = EE(_output_format='obfuscation').extract_email(sentence)
    #         print '#'*10
    #         print sentence.encode('ascii', 'ignore')
    #         print '#'*10
    #         print emails

"""
if __name__ == '__main__':
    # file = open('/Users/pszekely/Downloads/ht-email/ht-email.txt', 'r')
    # file = open('/Users/pszekely/Downloads/ht-email/jakarta.txt', 'r')
    # file = open('/Users/pszekely/Downloads/ht-email/test.txt', 'r')
    # file = open('/Users/pszekely/Downloads/ht-email/emails.txt', 'r')

    # line = "oikqlthi @ gmail commy GmaiL.. nude.ass33"
    # line = "@ashleyspecialselect@gmail .com"
    # line = "My personal gmail....wowboobs7"
    # line = "My personal gmail....cum2mom"
    # line = "[atmashraffreelancer gmail com]"
    # line = "\nSweetAbby90 at gmail\n" # this should be a separate pattern as it is all in one line
    # EE.extract_email(line)

    # path = 'emails_ground_truth.json'
    path = 'emails_ground_truth_obfuscation.json'
    with open(path) as gt_file:
        ground_truth = json.load(gt_file)

        correct = 0
        incorrect = 0
        not_recalled = 0
        incorrectly_extracted = []
        not_extracted = []
        for r in ground_truth:
            found = False
            sentence = r["sentence"]
            # print "as string: %s" % EE.extract_email(sentence, True)
            emails = EE(_output_format='obfuscation').extract_email(sentence)
            if len(emails) == 0:
                print "~~~ no extractions"
            for e in emails:
                found = True
                if e in r["emails"]:
                    correct += 1
                    print "+++ %s" % e
                else:
                    if len(r["emails"]) > 0:
                        incorrect += 1
                        r["extracted"] = e
                        incorrectly_extracted.append(r)
                    print "--- got: %s, expected: %s" % (e, r["emails"])
                print "\n"
            if not found and len(r["emails"]) > 0:
                not_recalled += 1
                r["extracted"] = ""
                not_extracted.append(r)

        print json.dumps(not_extracted, indent=4)
        print json.dumps(incorrectly_extracted, indent=4)
        print "\ncorrect %d, incorrect %d, not extracted: %d" % (correct, incorrect, not_recalled)
        print len(ground_truth)
"""