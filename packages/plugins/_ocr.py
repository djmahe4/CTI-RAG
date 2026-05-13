import os
import uuid
from pathlib import Path
from argparse import ArgumentParser

import fitz  # Fitz is pip install pymupDF.
import numpy as np  # Added import for numpy
from PIL import Image
from tqdm import tqdm
from rapidocr_onnxruntime import RapidOCR

from ..utils import logger, is_text_pdf


GOLBAL_STATE = {}


class OCRPlugin:
    """OCR Plugin"""

    def __init__(self, **kwargs):
        self.ocr = None
        self.det_box_thresh = kwargs.get('det_box_thresh', 0.3)

    def load_model(self):
        """Load OCR Model"""
        logger.info(f"Load OCR Model，Load only on first call")
        model_dir = os.path.join(os.getenv("MODEL_DIR", ""), "SWHL/RapidOCR")
        det_model_dir = os.path.join(model_dir, "PP-OCRv4/ch_PP-OCRv4_det_infer.onnx")
        rec_model_dir = os.path.join(model_dir, "PP-OCRv4/ch_PP-OCRv4_rec_infer.onnx")
        assert os.path.exists(model_dir), (
            f"Model file does not exist，Please download. SWHL/RapidOCR Present. {model_dir}，"
            "and confirm whether docker-compose.dev.yml Add MODEL_DIR Environmental variables"
        )
        self.ocr = RapidOCR(det_box_thresh=0.3, det_model_path=det_model_dir, rec_model_path=rec_model_dir)
        logger.info(f"OCR Plugin for det_box_thresh = {self.det_box_thresh} loaded.")

    def process_image(self, image):
        """
        Execute single imageOCRand extract text

        Args:
            image: Image Data，Support multiple formats：
                  - str: Image File Path
                  - PIL.Image: PILImage Object
                  - numpy.ndarray: numpyImage array

        Returns:
            str: Extracted text content
        """
        # Make sure the model is loaded
        if self.ocr is None:
            self.load_model()

        # Process different types of input images
        try:
            if isinstance(image, str):
                # Image path directly to OCR processing
                image_path = image
                is_temp_file = False
            else:
                # Create temporary file
                is_temp_file = True
                image_path = self._create_temp_image_file(image)

            # Execute OCR
            result, _ = self.ocr(image_path)

            # Clear temporary files
            if is_temp_file and os.path.exists(image_path):
                os.remove(image_path)

            # Extract text
            if result:
                text = '\n'.join([line[1] for line in result])
                return text
            else:
                logger.warning(f"OCRCannot recognize text content")
                return ""

        except Exception as e:
            logger.error(f"OCRProcess failed: {str(e)}")
            raise

    def _create_temp_image_file(self, image):
        """
        Save image data as temporary file

        Args:
            image: PIL.Imageornumpy.ndarrayImage data in format

        Returns:
            str: Temporary File Path
        """
        # Create directory for temporary files (if none exist)
        tmp_dir = os.path.join(os.getcwd(), 'tmp')
        os.makedirs(tmp_dir, exist_ok=True)

        # Generate temporary file path
        temp_filename = f'ocr_temp_{uuid.uuid4().hex[:8]}.png'
        image_path = os.path.join(tmp_dir, temp_filename)

        # Save files by image type
        if isinstance(image, Image.Image):
            # Save PIL Image Object to Temporary File
            image.save(image_path)
        elif isinstance(image, np.ndarray):
            # Convert Numpy arrays to PIL images and save them
            Image.fromarray(image).save(image_path)
        else:
            raise ValueError("Unsupported image type，Must be.PIL.ImageornumpyArray")

        return image_path

    def process_pdf(self, pdf_path):
        """
        ProcessingPDFFile and extract text
        :param pdf_path: PDFFile Path
        :return: Extracted Text
        """

        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        try:
            # Check for text PDF
            if is_text_pdf(pdf_path):
                logger.info(f"PDF file is text, use llama_index.readers.file to read")
                return pdfreader(pdf_path)

            # Convert PDF to Image
            filename = os.path.basename(pdf_path).split('.')[0]
            output_dir = os.path.join('saves', 'data', 'pdf2txt', filename)
            os.makedirs(output_dir, exist_ok=True)

            images = self.convert_imgs(pdf_path, output_dir)

            # Process each image and merge text
            all_text = []
            for img_path in tqdm(images, desc='to txt', ncols=100):
                text = self.process_image(img_path)
                all_text.append(text)

            return '\n\n'.join(all_text)

        except Exception as e:
            logger.error(f"PDF processing error: {str(e)}")
            return ""


    def convert_imgs(self, pdf_path, output_dir):
        imgs = []
        img_dir = os.path.join(output_dir, 'imgs')
        if not os.path.exists(img_dir):
            os.makedirs(img_dir)
            pdfDoc = fitz.open(pdf_path)
            totalPage = pdfDoc.page_count
            for pg in tqdm(range(totalPage), desc='to imgs', ncols=100):
                page = pdfDoc[pg]
                rotate = int(0)
                zoom_x = 2
                zoom_y = 2
                mat = fitz.Matrix(zoom_x, zoom_y).prerotate(rotate)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                img_filename = os.path.join(img_dir, f'images_{pg+1}.png')
                pix.save(img_filename)  # os.sep
                imgs.append(img_filename)
        else:
            img_names = sorted(os.listdir(img_dir))
            imgs = [os.path.join(img_dir, img_name) for img_name in img_names]

        return imgs

def get_state(task_id):
    return GOLBAL_STATE.get(task_id, {})


def pdfreader(file_path):
    """ReadPDFFile and ReturntextText"""
    assert os.path.exists(file_path), "File not found"
    assert file_path.endswith(".pdf"), "File format not supported"

    from llama_index.readers.file import PDFReader
    doc = PDFReader().load_data(file=Path(file_path))

    # Simple adjoining returns plain text
    text = "\n\n".join([d.get_content() for d in doc])
    return text

def plainreader(file_path):
    """Read normal text files and returntextText"""
    assert os.path.exists(file_path), "File not found"

    with open(file_path, "r") as f:
        text = f.read()
    return text



if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument('--pdf-path', type=str, required=True, help='Path to the PDF file')
    parser.add_argument('--return-text', action='store_true', help='Return the extracted text')
    args = parser.parse_args()

    ocr = OCRPlugin()
    text = ocr.process_pdf(args.pdf_path)
    print(text)
