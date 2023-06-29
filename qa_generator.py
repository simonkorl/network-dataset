import os
import openai
import logging
import pandas as pd
import opencc
import time
import re
import argparse
from utils import set_proxy, test_proxy, set_openai_key


QUESTION_PROMPT = "请根据以下文本生成问题，尽可能使用简体中文，问题表述需要清晰详细\n\n文本: {context}\n\n问题:\n1."
ANSWER_PROMPT = "根据以下文本生成问题的答案，尽可能使用简体中文\n\n文本: {context}\n\n问题:\n{questions}\n\n答案:\n1."


def gen_questions_by_davinci(context, max_tokens=500):
    try:
        response = openai.Completion.create(
            # engine="davinci-instruct-beta-v3",
            engine="text-davinci-003",
            prompt=QUESTION_PROMPT.format(context=context),
            temperature=0,
            max_tokens=max_tokens,
            top_p=1,
            frequency_penalty=0,
            presence_penalty=0,
            stop=["\n\n"]
        )
        return response['choices'][0]['text']
    except Exception as e:
        logging.error(e)
        return ""


def gen_questions_by_chat(context, max_tokens=500):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "user",
                    "content": QUESTION_PROMPT.format(context=context)
                }
            ],
            temperature=0,
            max_tokens=500,
            top_p=1,
            frequency_penalty=0,
            presence_penalty=0,
            stop=["\n\n"]
        )
        return response.choices[0].message.content
    except Exception as e:
        logging.error(e)
        return ""
    

def gen_answers_by_davinci(row, max_tokens=500):
    try:
        response = openai.Completion.create(
            # engine="davinci-instruct-beta-v3",
            engine="text-davinci-003",
            prompt=ANSWER_PROMPT.format(context=row.context, questions=row.questions),
            temperature=0,
            max_tokens=max_tokens,
            top_p=1,
            frequency_penalty=0,
            presence_penalty=0,
            stop=["\n\n"]
        )
        return response['choices'][0]['text']
    except Exception as e:
        logging.error(e)
        return ""
    

def gen_answers_by_chat(row, max_tokens=500):
    try:
        response = openai.ChatCompletion.create(
            model = "gpt-3.5-turbo",
            messages=[
                {
                    "role": "user",
                    "content": ANSWER_PROMPT.format(context=row.context, questions=row.questions)
                }
            ],
            temperature=0,
            max_tokens=max_tokens,
            top_p=1,
            frequency_penalty=0,
            presence_penalty=0
        )
        return response.choices[0].message.content
    except Exception as e:
        logging.error(e)
        return ""
    

def gen_qa(csv_filename, model="gpt"):
    df = pd.read_csv(csv_filename)
    # check fields
    if "context" not in df.columns:
        assert "summary" in df.columns and "content" in df.columns,\
            "csv file must contain 'context', or both 'summary' and 'content' fields"
        df["context"] = "summary: " +  df.summary + "\n" +  "content: " + df.content
    
    # generate questions based on context
    start_time = time.time()
    if model == "davinci":
        df["questions"] = df.context.apply(gen_questions_by_davinci)
    else:
        df["questions"] = df.context.apply(gen_questions_by_chat)
    df["questions"] = "1." + df.questions
    print("generate questions time: ", time.time() - start_time)

    # save intermediate result
    df.to_csv(csv_filename.replace(".csv", "-questions.csv"), index=False)

    # generate answers based on context and questions
    start_time = time.time()
    if model == "davinci":
        df["answers"] = df.apply(gen_answers_by_davinci, axis=1)
    else:
        df["answers"] = df.apply(gen_answers_by_chat, axis=1)
    df["answers"] = "1." + df.answers
    print("generate answers time: ", time.time() - start_time)

    # save raw qa
    save_filename = csv_filename.replace(".csv", "-qa-raw.csv")
    df.to_csv(save_filename, index=False)
    return save_filename


converter = opencc.OpenCC('t2s.json')


def split_qa(csv_filename, aspect_list=[]):
    df = pd.read_csv(csv_filename)
    # split raw qa into qa pairs
    question_list, answer_list = [], []
    asp_score_dict = {f"{asp}_score": [] for asp in aspect_list}
    for idx, row in df.iterrows():
        questions = row.questions.split("\n")
        answers = row.answers.split("\n")
        min_len = min(len(questions), len(answers))
        question_list.extend(list(map(lambda x: re.sub(r"^[0-9]+\.", "", x).strip(" \""), questions[:min_len])))
        answer_list.extend(list(map(lambda x: re.sub(r"^[0-9]+\.", "", x).strip(" \""), answers[:min_len])))
        for asp in aspect_list:
            asp_score_dict[f"{asp}_score"].extend(
                [(row[f"{asp}_q_score"] + row[f"{asp}_a_score"]) / 2] * min_len
            )
    
    qa_dict = {"question": question_list, "answer": answer_list}
    for asp in aspect_list:
        qa_dict[f"{asp}_score"] = asp_score_dict[f"{asp}_score"]

    save_filename = csv_filename.replace("-qa-raw.csv", "-qa.csv")
    pd.DataFrame(qa_dict).to_csv(save_filename, index=False)
    return save_filename


def filter_qa(csv_filename, min_len = 10, max_len = 300):
    # filter qa pairs
    print("before filter: ", qa_df.shape)
    # remove too short or too long qa pairs
    qa_df = qa_df[(qa_df.question.str.len() >= min_len) & (qa_df.question.str.len() <= max_len)]
    qa_df = qa_df[(qa_df.answer.str.len() >= min_len) & (qa_df.answer.str.len() <= max_len)]
    print("after length filter: ", qa_df.shape)
    # remove questions not end with question mark
    qa_df = qa_df[qa_df.question.str.endswith("？")]
    print("after question mark filter: ", qa_df.shape)
    # remove answers not end with period
    qa_df = qa_df[qa_df.answer.str.endswith("。")]
    print("after period filter: ", qa_df.shape)
    # remove duplicated qa pairs
    qa_df = qa_df.drop_duplicates(subset=["question", "answer"])
    print("after duplicate filter: ", qa_df.shape)

    # convert traditional chinese to simplified chinese
    qa_df.question = qa_df.question.apply(lambda x: converter.convert(x))
    qa_df.answer = qa_df.answer.apply(lambda x: converter.convert(x))

    # save filtered qa
    save_filename = csv_filename.replace(".csv", "-filtered.csv")
    qa_df.to_csv(save_filename, index=False)
    return save_filename


parser = argparse.ArgumentParser()
parser.add_argument("--input", type=str, required=True, help="input csv filename")
parser.add_argument("--model", type=str, default="gpt", help="model name, `davinci` or `gpt`")
parser.add_argument("--proxy", type=str, default=None, help="proxy address")


def main():
    args = parser.parse_args()

    if args.proxy is not None:
        set_proxy(proxy=args.proxy)
    else:
        set_proxy()
    assert test_proxy(), "proxy is not working"
    set_openai_key()

    save_filename = gen_qa(args.input, model=args.model)
    save_filename = split_qa(save_filename)
    filter_qa(save_filename)