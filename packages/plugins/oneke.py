# readmore: https://github.com/zjunlp/DeepKE/blob/main/example/llm/OneKE.md
import os
import json
import torch
import dotenv
from transformers import (
    AutoConfig,
    AutoTokenizer,
    AutoModelForCausalLM,
    GenerationConfig,
    BitsAndBytesConfig
)

from ..utils import logger

dotenv.load_dotenv()

instruction_mapper = {
    'NERzh': "You are an expert in named entity recognition. Please extract entities that match the schema definition from the input. Return an empty list if the entity type does not exist. Please respond in the format of a JSON string.",
    'REzh': "You are an expert in relationship extraction. Please extract relationship triples that match the schema definition from the input. Return an empty list for relationships that do not exist. Please respond in the format of a JSON string.",
    'EEzh': "You are an expert in event extraction. Please extract events from the input that conform to the schema definition. Return an empty list for events that do not exist, and return NAN for arguments that do not exist. If an argument has multiple values, please return a list. Respond in the format of a JSON string.",
    'EETzh': "You are an expert in event extraction. Please extract event types and event trigger words from the input that conform to the schema definition. Return an empty list for non-existent events. Please respond in the format of a JSON string.",
    'EEAzh': "You are an expert in event argument extraction. Please extract event arguments and their roles from the input that conform to the schema definition, which already includes event trigger words. If an argument does not exist, return NAN or an empty dictionary. Please respond in the format of a JSON string.",
    'KGzh': "You are an expert in structured knowledge systems for graph entities. Based on the schema description of the input entity type, you extract the corresponding entity instances and their attribute information from the text. Attributes that do not exist should not be output. If an attribute has multiple values, a list should be returned. The results should be output in a parsable JSON format.",
    'NERen': "You are an expert in named entity recognition. Please extract entities that match the schema definition from the input. Return an empty list if the entity type does not exist. Please respond in the format of a JSON string.",
    'REen': "You are an expert in relationship extraction. Please extract relationship triples that match the schema definition from the input. Return an empty list for relationships that do not exist. Please respond in the format of a JSON string.",
    'EEen': "You are an expert in event extraction. Please extract events from the input that conform to the schema definition. Return an empty list for events that do not exist, and return NAN for arguments that do not exist. If an argument has multiple values, please return a list. Respond in the format of a JSON string.",
    'EETen': "You are an expert in event extraction. Please extract event types and event trigger words from the input that conform to the schema definition. Return an empty list for non-existent events. Please respond in the format of a JSON string.",
    'EEAen': "You are an expert in event argument extraction. Please extract event arguments and their roles from the input that conform to the schema definition, which already includes event trigger words. If an argument does not exist, return NAN or an empty dictionary. Please respond in the format of a JSON string.",
    'KGen': "You are an expert in structured knowledge systems for graph entities. Based on the schema description of the input entity type, you extract the corresponding entity instances and their attribute information from the text. Attributes that do not exist should not be output. If an attribute has multiple values, a list should be returned. The results should be output in a parsable JSON format.",
}

split_num_mapper = {
    'NER':6, 'RE':4, 'EE':4, 'EET':4, 'EEA':4, 'KG':1
}

class OneKE:

    def __init__(self, config=None):

        self.config = config
        model_name_or_path = config.model_local_paths.get('zjunlp/OneKE', "zjunlp/OneKE")
        logger.info(f"Loading KGC model OneKE from {model_name_or_path}")

        model_config = AutoConfig.from_pretrained(model_name_or_path, trust_remote_code=True)
        self.tokenizer = AutoTokenizer.from_pretrained(model_name_or_path, trust_remote_code=True)

        self.quantization_config=BitsAndBytesConfig(
            load_in_4bit=True,
            llm_int8_threshold=6.0,
            llm_int8_has_fp16_weight=False,
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4",
        )

        self.generate_config = GenerationConfig(
            max_length=1024,
            max_new_tokens=512,
            return_dict_in_generate=True
        )

        self.model = AutoModelForCausalLM.from_pretrained(
            model_name_or_path,
            config=model_config,
            device_map="auto",
            quantization_config=self.quantization_config,
            torch_dtype=torch.bfloat16,
            trust_remote_code=True,
        )
        self.model.eval()

    def construct_input(self, text, schema, task, language="zh", use_split=False):
        if use_split:
            split_num = split_num_mapper[task]
            if isinstance(schema, dict):
                schema_keys = list(schema.keys())
                schema_keys = [schema_keys[i:i+split_num] for i in range(0, len(schema_keys), split_num)]
                schema = [{k: schema[k] for k in keys} for keys in schema_keys]
            else:
                schema = [schema[i:i+split_num] for i in range(0, len(schema), split_num)]
        else:
            schema = [schema]

        sintructs = []
        for s in schema:
            sintruct = json.dumps({
                "instruction": instruction_mapper[task+language],
                "schema": s,
                "input": text,
            }, ensure_ascii=False)
            sintructs.append(sintruct)

        return sintructs

    def predict(self, text, schema, task, language="zh", use_split=False):
        sintructs = self.construct_input(text, schema, task, language, use_split)
        outputs = []
        for sintruct in sintructs:
            input_ids = self.tokenizer.encode(sintruct, return_tensors="pt").to(self.model.device)
            input_length = input_ids.size(1)

            generation_output = self.model.generate(
                input_ids=input_ids,
                generation_config=self.generate_config,
                pad_token_id=self.tokenizer.eos_token_id
            )
            generation_output = generation_output.sequences[0]
            generation_output = generation_output[input_length:]
            output = self.tokenizer.decode(generation_output, skip_special_tokens=True)

            outputs.append(output)

        return outputs

    def processing_text_to_kg(self, text_or_path, output_path):
        for chunk in read_and_process_chars(text_or_path):

            text = chunk
            schema = [
                {
                    "entity_type": "Food",
                    "attributes": {
                        "Name": "Name of food, including brand names, common or technical chemical names",
                        "Classification": "Type of food, such as fruit, vegetable, meat, cereal, spice, additive, probiotic, etc.",
                        "Component": "Main ingredients of food, listing natural components, additives, preservatives, nutritional fortifiers, etc.",
                        "Nutritional value": "Nutritional composition, summarizing energy and major nutrients like protein, fat, carbohydrates, vitamins, and minerals",
                        "Process": "Treatment or preparation method, including daily cooking, processing, and laboratory preparation",
                        "Effect": "Impact on health or body, possible efficacy or uses"
                    }
                }
            ]
            task = "KG"
            output = self.predict(text=text, schema=schema, task=task, language="zh")
            formatted_output = parse_and_format_output(output=output, task_type=task)

            with open(output_path, 'a+', encoding='utf-8') as f:
                for entry in formatted_output:
                    f.write(json.dumps(entry, ensure_ascii=False) + '\n')

        print(f"Prediction results added to {output_path} file.")
        return output_path

def read_and_process_chars(file_path, char_size=512, overlap_size=100):
    buffer = ""
    with open(file_path, 'r', encoding='utf-8') as file:
        while True:
            chunk = file.read(char_size)
            if not chunk:  # 文件读取完毕
                if buffer:
                    yield buffer
                break
            chunk = chunk.replace('\n', '').replace('\r', '')  # 去除换行符
            buffer += chunk
            while len(buffer) >= char_size:
                yield buffer[:char_size]
                buffer = buffer[char_size - overlap_size:]

def parse_and_format_output(output, task_type):
    formatted_output = []

    for entry in output:
        try:
            # Check if the entry is a valid JSON string
            if isinstance(entry, str) and entry.strip().startswith('{') and entry.strip().endswith('}'):
                parsed_entry = json.loads(entry)

                if task_type == "KG":
                    for entity_type, entities in parsed_entry.items():
                        for entity_name, attributes in entities.items():
                            for attribute_name, attribute_values in attributes.items():
                                if isinstance(attribute_values, list):
                                    for value in attribute_values:
                                        formatted_output.append({
                                            "h": entity_name,
                                            "t": value,
                                            "r": attribute_name
                                        })
                                else:
                                    formatted_output.append({
                                        "h": entity_name,
                                        "t": attribute_values,
                                        "r": attribute_name
                                    })
                elif task_type == "RE":
                    for relation_type, pairs in parsed_entry.items():
                        for pair in pairs:
                            formatted_output.append({
                                "h": pair["subject"],
                                "t": pair["object"],
                                "r": relation_type
                            })
            else:
                raise json.JSONDecodeError("Invalid JSON format", entry, 0)
        except json.JSONDecodeError as e:
            print(f"JSONDecodeError: {e} - Skipping entry")
            continue
        except TypeError as e:
            print(f"TypeError: {e} - Skipping entry")
            continue
        except AttributeError as e:
            print(f"AttributeError: {e} - Skipping entry")
            continue

    return formatted_output


if __name__ == "__main__":
    oneke = OneKE()
    oneke.processing_text_to_kg("asdasdadadsad", 'kg.jsonl')

    file_path = ''
    output_path = ''
    text = ""
    task = "KG"
    for chunk in read_and_process_chars(file_path):

        text = chunk

        # schema = {
        #     "Definition": "Describes the origin of food, traditional production methods, cultural symbolism, or the definition/meaning of food or related items.",
        #     "Components": "Describes the parts or ingredients of food, including major components, trace elements, additives, etc.",
        #     "Function": "Describes the function or effect of food or its components, including health impact, culinary use, medicinal value, etc.",
        #     "Attributes": "Describes characteristics or properties like nutritional value, taste (e.g., rich, light), preservation methods (e.g., refrigeration, drying).",
        #     "Category": "Describes the type or category of food, revealing its classification system and application differences."
        # }

        schema = [
            {
                "entity_type": "Food",
                "attributes": {
                    "Name": "Name of food, including brand names, common or technical chemical names",
                    "Classification": "Type of food, such as fruit, vegetable, meat, cereal, spice, additive, probiotic, etc.",
                    "Component": "Main ingredients of food, listing natural components, additives, preservatives, nutritional fortifiers, etc.",
                    "Nutritional value": "Nutritional composition, summarizing energy and major nutrients like protein, fat, carbohydrates, vitamins, and minerals",
                    "Process": "Treatment or preparation method, including daily cooking, processing, and laboratory preparation",
                    "Effect": "Impact on health or body, possible efficacy or uses"
                }
            }
        ]

        output = oneke.predict(text=text, schema=schema, task=task, language="zh")
        formatted_output = parse_and_format_output(output=output, task_type=task)

        with open(output_path, 'a+', encoding='utf-8') as f:
            for entry in formatted_output:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')

    print(f"Prediction results added to {output_path} file.")