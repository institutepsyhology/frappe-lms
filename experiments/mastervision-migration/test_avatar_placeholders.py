"""Pure exact default-avatar recognition; no fetching or source-account data."""
import unittest

from avatar_placeholders import is_known_avatar_url


class AvatarPlaceholderTests(unittest.TestCase):
    def test_only_confirmed_default_avatars_and_encoded_namespace_match(self):
        urls=('https://f1.autoweboffice.ru/iomp/unnamed.jpeg',
              'https://f1.autoweboffice.ru/another_namespace/unnamed.jpeg',
              'https://f1.autoweboffice.ru/%D1%83%D1%80%D0%BE%D0%BA%D0%B8/course%20one/unnamed.jpeg',
              'https://getcourse.ru/public/img/default_profile_50.png')
        for url in urls:
            with self.subTest(url=url):self.assertIs(is_known_avatar_url(url),True)

    def test_other_files_hosts_macros_and_missing_values_are_not_defaults(self):
        values=(None,False,{},'', '{avatar_url}', 'unnamed.jpeg',
                'https://f1.autoweboffice.ru/iomp/unnamed.jpg',
                'https://f1.autoweboffice.ru/iomp/Unnamed.jpeg',
                'https://f1.autoweboffice.ru/iomp/real.jpg',
                'https://f1.autoweboffice.ru/iomp/%75nnamed.jpeg',
                'https://f2.autoweboffice.ru/iomp/unnamed.jpeg',
                'https://f1.autoweboffice.com/iomp/unnamed.jpeg',
                'https://example.test/iomp/unnamed.jpeg',
                'https://f1.autoweboffice.ru.evil.test/iomp/unnamed.jpeg',
                'https://getcourse.ru.evil.test/public/img/default_profile_50.png',
                'https://getcourse.ru/public/img/default_profile_100.png',
                'https://getcourse.ru/other/img/default_profile_50.png',
                'https://getcourse.ru/public/img/%64efault_profile_50.png')
        for value in values:
            with self.subTest(value=value):self.assertIs(is_known_avatar_url(value),False)

    def test_credentials_ports_queries_fragments_and_invalid_paths_never_match(self):
        valid='https://f1.autoweboffice.ru/iomp/unnamed.jpeg'
        values=(valid+'?key=test',valid+'?',valid+'#test',valid+'#',
                valid.replace('https:','http:'),valid.replace('//f1.','//u:p@f1.'),
                valid.replace('.ru/','.ru:443/'),valid.replace('/iomp/','/../'),
                valid.replace('/iomp/','/%2e%2e/'),valid.replace('/iomp/','/%252e%252e/'),
                valid.replace('/iomp/','/%2fprivate/'),valid.replace('/iomp/','/%5cprivate/'),
                valid.replace('/iomp/','/%00/'),valid.replace('/iomp/','/%XX/'),
                valid.replace('/iomp/','/%FF/'),valid.replace('/iomp/','//'),
                'https://getcourse.ru/public/img/default_profile_50.png?query=yes',
                'https://u:p@getcourse.ru/public/img/default_profile_50.png',
                'https://getcourse.ru:443/public/img/default_profile_50.png')
        for value in values:
            with self.subTest(value=value):self.assertIs(is_known_avatar_url(value),False)


if __name__=='__main__':
    unittest.main()
