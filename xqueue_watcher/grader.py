"""
Implementation of a grader compatible with XServer
"""
import imp
import sys
import cgi
import time
import json
from path import path
import logging
import multiprocessing
from statsd import statsd


def format_errors(errors):
    esc = cgi.escape
    error_string = ''
    error_list = [esc(e) for e in errors or []]
    if error_list:
        items = u'\n'.join([u'<li><pre>{0}</pre></li>\n'.format(e) for e in error_list])
        error_string = u'<ul>\n{0}</ul>\n'.format(items)
        error_string = u'<div class="result-errors">{0}</div>'.format(error_string)
    return error_string


def to_dict(result):
    # long description may or may not be provided.  If not, don't display it.
    # TODO: replace with mako template
    esc = cgi.escape
    if result[1]:
        long_desc = u'<p>{0}</p>'.format(esc(result[1]))
    else:
        long_desc = u''
    return {'short-description': esc(result[0]),
            'long-description': long_desc,
            'correct': result[2],   # Boolean; don't escape.
            'expected-output': esc(result[3]),
            'actual-output': esc(result[4])
            }


class Grader(object):
    results_template = u"""
<div class="test">
<header>Test results</header>
  <section>
    <div class="shortform">
    {status}
    </div>
    <div class="longform">
      {errors}
      {results}
    </div>
  </section>
</div>
"""

    results_correct_template = u"""
      <div class="result-output result-correct">
        <h4>{short-description}</h4>
        <div style="width: calc(50% - 10px); display: inline-block;">
            <dt>Program Output:</dt>
            <dl>
                <dd class="result-actual-output"  style="margin-left: 0;">
                   <pre style="white-space: no-wrap;">{actual-output}</pre>
                </dd>
            </dl>   
        </div>
        <div style="width: calc(50% - 10px); display: inline-block;">
            <dt>Expected Output:</dt>
            <dl>
                <dd style="margin-left: 0;">
                    <pre style="white-space: no-wrap;">{expected-output}</pre>
                </dd>
            </dl>        
        </div>
      </div>
"""

    results_incorrect_template = u"""
      <div class="result-output result-incorrect">
        <h4>{short-description}</h4>
        <div style="width: calc(50% - 10px); display: inline-block;">
            <dt>Program Output:</dt>
            <dl>
        
            <dd class="result-actual-output"  style="margin-left: 0;">
               <pre style="white-space: no-wrap;">{actual-output}</pre>
             </dd>
        </dl>   
        </div>
        <div style="width: calc(50% - 10px); display: inline-block;">
            <dt>Correct Output:</dt>
            <dl>
                <dd style="margin-left: 0;">
                    <pre style="white-space: no-wrap;">{expected-output}</pre>
                </dd>
            </dl>        
        </div>
      </div>
"""

    def __init__(self, grader_root='/tmp/', fork_per_item=True, logger_name=__name__):
        """
        grader_root = root path to graders
        fork_per_item = fork a process for every request
        logger_name = name of logger
        """
        self.log = logging.getLogger(logger_name)
        self.grader_root = path(grader_root)

        self.fork_per_item = fork_per_item

    def __call__(self, content):
        if self.fork_per_item:
            q = multiprocessing.Queue()
            proc = multiprocessing.Process(target=self.process_item, args=(content, q))
            proc.start()
            proc.join()
            reply = q.get_nowait()
            if isinstance(reply, Exception):
                raise reply
            else:
                return reply
        else:
            return self.process_item(content)

    def grade(self, grader_path, grader_config, student_response):
        raise NotImplementedError("no grader defined")

    def process_item(self, content, queue=None):
        try:
            statsd.increment('xqueuewatcher.process-item')
            body = content['xqueue_body']
            files = content['xqueue_files']

            # Delivery from the lms
            body = json.loads(body)
            student_response = body['student_response']
            payload = body['grader_payload']
            student_info = body['student_info']

            try:
                grader_config = json.loads(payload)
            except ValueError as err:
                # If parsing json fails, erroring is fine--something is wrong in the content.
                # However, for debugging, still want to see what the problem is
                statsd.increment('xqueuewatcher.grader_payload_error')

                self.log.debug("error parsing: '{0}' -- {1}".format(payload, err))
                raise

            grader_config['is_staff'] = json.loads(student_info)['is_staff']
            self.log.debug("Processing submission, grader payload: {0}".format(grader_config))
            relative_grader_path = grader_config['grader']
            grader_path = (self.grader_root / relative_grader_path).abspath()
            start = time.time()
            results = self.grade(grader_path, grader_config, student_response)

            statsd.histogram('xqueuewatcher.grading-time', time.time() - start)

            # Make valid JSON message
            reply = {}
            for key in results.keys():
                reply[key] = {'correct': results[key]['correct'],
                     'score': results[key]['score'],
                     'msg': self.render_results(results[key])}

            statsd.increment('xqueuewatcher.replies (non-exception)')
        except Exception as e:
            self.log.exception("process_item")
            if queue:
                queue.put(e)
            else:
                raise
        else:
            if queue:
                queue.put(reply)
            return reply

    def render_results(self, results):
        output = []
        test_results = [to_dict(r) for r in results['tests']]
        for result in test_results:
            if result['correct']:
                template = self.results_correct_template
            else:
                template = self.results_incorrect_template

            result['actual-output'].replace('\n', '<br />')
            result['actual-output'] = result['actual-output'].replace(' ', '&nbsp;')
            result['actual-output'] = result['actual-output'].replace('\n', '<br />')
            result['expected-output'] = result['expected-output'].replace(' ', '&nbsp;')
            result['expected-output'] = result['expected-output'].replace('\n', '<br />')
            output += template.format(**result)

        errors = format_errors(results['errors'])

        status = 'INCORRECT'
        if errors:
            status = 'ERROR'
        elif results['correct']:
            status = 'CORRECT'

        return self.results_template.format(status=status,
                                            errors=errors,
                                            results=''.join(output))
