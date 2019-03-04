from xqueue_watcher.grader import Grader
import subprocess
import time
import re
import os

def run_as_subprocess(cmd, compiling=False, running_code=False, timeout=None):
    """
    runs the subprocess and execute the command. if timeout is given kills the
    process after the timeout period has passed. compiling and running code flags
    helps to return related message in exception
    """

    if timeout:
        cmd = 'timeout --signal=SIGKILL {0} {1}'.format(timeout, cmd)

    output, error = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True
    ).communicate()

    if error and compiling:
        raise Exception(error)
    elif error and running_code and 'Killed' in error:
        raise Exception('Time limit exceeded.')
    elif error and running_code:
        raise Exception(error)

    return output


def respond_with_error(message):
    """
    returns error response with message
    """
    return {
        'correct': False,
        'score': 0,
        'errors': [message],
        'tests': []
    }


def execute_code(lang, code_file_name, code_full_file_name, code_file_path, input_file, timeout):
    """
    compiles the code, runs the code for python, java and c++ and returns output of the code
    """
    if lang == 'py':
        output = run_as_subprocess('python3 ' + code_full_file_name + input_file, running_code=True, timeout=timeout)

    elif lang == 'java':
        print 'javac -cp {0} {1}'.format(TestGrader.SECRET_DATA_DIR + "json-simple-1.1.1.jar", code_full_file_name)
        run_as_subprocess('javac -cp {0} {1}'.format(TestGrader.SECRET_DATA_DIR + "json-simple-1.1.1.jar", code_full_file_name), compiling=True)
        output = run_as_subprocess(
            'java -cp {0} {1}{2}'.format(TestGrader.TMP_DATA_DIR + ":" + TestGrader.SECRET_DATA_DIR + "json-simple-1.1.1.jar", code_file_name, input_file),
            running_code=True, timeout=timeout
        )

    elif lang == 'cpp':
        run_as_subprocess('g++ ' + code_full_file_name + ' -o ' + code_file_path, compiling=True)
        output = run_as_subprocess('./' + code_file_path + input_file, running_code=True, timeout=timeout)

    else:
        raise Exception
    return output


def detect_code_language(student_response, code_file_name):
    """
    detects language using guesslang module and raises exception if
    language is not in one of these. JAVA, C++, PYTHON. for java
    replaces the public class name with file name to execute the code.
    LIMIT: Expects only one public class in Java solution
    """
    output = run_as_subprocess("echo '" + student_response + "' | guesslang")

    if 'Python' in output:
        lang = "py"
    elif 'Java' in output:
        lang = 'java'
        student_response = re.sub(
            'public class (.*) {', 'public class {0} {{'.format(code_file_name), student_response
        )
    elif 'C++' in output:
        lang = 'cpp'
    else:
        raise Exception('Language can only be C++, Java or Python.')
    return lang, student_response


def write_code_file(student_response, full_code_file_name):
    """
    accepts code and file name to where the code will be written.
    """
    f = open(full_code_file_name, 'w')
    f.write(student_response)
    f.close()


def compare_outputs(actual_output, expected_output_file):
    """
    compares actual and expected output line by line after stripping
    any whitespaces at the ends. Raises Exception if outputs do not match
    otherwise returns response of correct answer
    """
    expected_output = open(expected_output_file, 'r').read().strip()
    actual_output = actual_output.strip()

    expected_output_splited = expected_output.split('\n')
    actual_output_splited = actual_output.split('\n')

    if actual_output_splited != expected_output_splited:
        return {
            'correct': False,
            'score': 0,
            'errors': [],
            'tests': [["", "", False, expected_output, actual_output]]
        }
    else:
        return {
            'correct': True,
            'score': 1,
            'errors': [],
            'tests': [["", "", True, expected_output, actual_output]]
        }

def run_test_cases(lang, code_file_name, full_code_file_name, code_file_path, input_file_argument, expected_output_file, timeout):
    # Run Sample Test Case
    try:
        output = execute_code(lang, code_file_name, full_code_file_name, code_file_path, input_file_argument, timeout)
        return compare_outputs(output, expected_output_file)
    except Exception as e:
        return respond_with_error(e.message)

class TestGrader(Grader):
    SECRET_DATA_DIR = "test_grader/secret_data/"
    TMP_DATA_DIR = "test_grader/tmp_data/"

    def grade(self, grader_path, grader_config, student_response):

        code_file_name = "code_" + str(int(time.time()))
        code_file_path = TestGrader.TMP_DATA_DIR + code_file_name

        try:
            lang, student_response = detect_code_language(student_response, code_file_name)
            full_code_file_name = '{0}.{1}'.format(code_file_path, lang)
            write_code_file(student_response, full_code_file_name)
        except Exception as exc:
            return respond_with_error(exc.message)

        sample_input_file_argument = ' {0}{1}-sample.in'.format(self.SECRET_DATA_DIR, grader_config['problem_name'])
        sample_expected_output_file = '{0}{1}-sample.out'.format(self.SECRET_DATA_DIR, grader_config['problem_name'])
        input_file_argument = ' {0}{1}.in'.format(self.SECRET_DATA_DIR, grader_config['problem_name'])
        expected_output_file = '{0}{1}.out'.format(self.SECRET_DATA_DIR, grader_config['problem_name'])

        sample_test_case_result = run_test_cases(lang, code_file_name, full_code_file_name, code_file_path, sample_input_file_argument, sample_expected_output_file, grader_config['timeout'])
        secret_test_case_result = run_test_cases(lang, code_file_name, full_code_file_name, code_file_path, input_file_argument, expected_output_file, grader_config['timeout'])

        if sample_test_case_result["tests"]:
            sample_test_case_result["tests"][0].append("sample")
            secret_test_case_result["tests"][0].append("staff")
            sample_test_case_result["tests"].append(secret_test_case_result["tests"][0])

        if os.path.exists(full_code_file_name):
            os.remove(full_code_file_name)
        if os.path.exists(code_file_name + ".class"):
            os.remove(code_file_name + ".class")
        if os.path.exists(code_file_name + ".out"):
            os.remove(code_file_name + ".out")

        return sample_test_case_result
