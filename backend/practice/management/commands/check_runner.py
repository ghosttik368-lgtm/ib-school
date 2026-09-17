from django.core.management.base import BaseCommand, CommandError
from practice.engine import check_docker, judge, RunnerError


class Command(BaseCommand):
    help = 'Проверка реального Docker: компиляция, ответ, ошибка, лимиты и изоляция.'
    def add_arguments(self, parser):
        parser.add_argument("--repeat", type=int, default=1, choices=range(1,51))

    def handle(self, *args, **options):
        try:
            check_docker()
            cases = [
                ('Сумма', '#include <iostream>\nint main(){long long a,b;std::cin>>a>>b;std::cout<<a+b;}', [{'input':'2 3','output':'5'},{'input':'-8 3','output':'-5'}], 'accepted'),
                ('Неверный ответ', 'int main(){}', [{'input':'','output':'42'}], 'wrong_answer'),
                ('Ошибка компиляции', 'int main( broken', [{'input':'','output':''}], 'compile_error'),
                ('Бесконечный цикл', 'int main(){while(true){}}', [{'input':'','output':''}], 'time_limit'),
                ('Ограничение вывода', '#include <cstdio>\nint main(){while(true) puts("xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx");}', [{'input':'','output':''}], 'output_limit'),
            ]
            for title, code, tests, expected in cases:
                result = judge(code, tests, 1, 64)
                if result['status'] != expected: raise CommandError(f'{title}: ожидалось {expected}, получено {result}')
                self.stdout.write(self.style.SUCCESS(title + ': OK'))
            isolation = '#include <unistd.h>\n#include <fstream>\n#include <iostream>\nint main(){std::ofstream f("/opt/forbidden");std::ifstream secret("/var/run/docker.sock");std::cout<<(getuid()!=0)<<" "<<(!f)<<" "<<(!secret);}'
            if judge(isolation, [{'input':'','output':'1 1 1'}], 2, 64)['status']!='accepted':
                raise CommandError('Проверка ограничений контейнера не пройдена.')
            for n in range(options['repeat']):
                result = judge(cases[0][1], [], 2, 64, run_input=f'{n} 7')
                if result['status'] != 'run_ok' or result['stdout'].strip() != str(n+7):
                    raise CommandError(f'Повторный запуск {n+1}: {result}')
            self.stdout.write(self.style.SUCCESS(f"Повторные запуски: {options['repeat']} OK. Все проверки Docker пройдены."))
        except RunnerError as exc: raise CommandError(str(exc))
