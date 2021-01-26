# A script to parse flickr datasets/autotags
# Download all: python tag_analysis.py --all_images --img_dir /project_data/ramanan/yfcc100m --min_size 10; No checking of broken paths
from io import BytesIO
import os
import json
import time
import argparse
from dataclasses import dataclass

from PIL import Image
import requests
from tqdm import tqdm
import pickle
from datetime import datetime
from dateutil import parser
import shutil
import random
import imagesize

import matplotlib.pyplot as plt
import numpy as np

from make_html import make_index_html, make_table_html

SCORE_BUCKET = [0.5, 0.625, 0.75, 0.875]
# ASPECT_RATIO_BUCKET = [1., 2., 3., 4., 5.]
WEIRD_ASPECT_RATIO = 2.0


argparser = argparse.ArgumentParser()
argparser.add_argument("--img_dir", 
                        default='./yfcc100m/data',
                        help="The yfcc100M dataset store location")
argparser.add_argument("--data_file", 
                        default='./yfcc100m/yfcc100m_dataset',
                        help="The yfcc100M dataset file ")
argparser.add_argument("--auto_file",
                        default='./yfcc100m/yfcc100m_autotags-v1', 
                        help="The autotag file")
argparser.add_argument("--exif_file",
                        default='./yfcc100m/yfcc100m_exif', 
                        help="The exif file")
argparser.add_argument("--hash_file",
                        default='./yfcc100m/yfcc100m_hash', 
                        help="The hash file")
argparser.add_argument("--hash_pickle",
                        default='./yfcc100m/yfcc100m_hash.pickle', 
                        help="The hash dictionary pickle object")
argparser.add_argument("--lines_file",
                        default='./yfcc100m/yfcc100m_lines', 
                        help="The lines file")
argparser.add_argument("--size_option",
                        default='original', choices=['original'],
                        help="Whether to use the original image size (max edge has 500 px).")
argparser.add_argument("--max_images",
                        type=int, default=10000,
                        help="The maximum images to store")
argparser.add_argument("--original_size",
                        action='store_true',
                        help="Whether to use the original image size.")
argparser.add_argument("--min_edge",
                        type=int, default=0,
                        help="Images with edge shorter than min_edge will be ignored.")
argparser.add_argument("--min_size",
                        type=int, default=2100,
                        help="Images with size smaller than min_size will be ignored.")
argparser.add_argument("--fetch_by_tag",
                        type=str, default=None,
                        help="Images with tag fetch_by_tag .")
argparser.add_argument("--random_images",
                        action='store_true',
                        help="Random subset of images .")
argparser.add_argument("--all_images",
                        action='store_true',
                        help="Store all images.")


from flickr_parsing import AllImages, Criteria, Metadata, MetadataObject, IDX_TO_NAME, IDX_LIST, plot_time_buckets
     
class _Metadata():
    def __init__(self, meta):
        self.meta = meta

    def __hash__(self):
        return hash(self.meta.ID)

    def __eq__(self, other):
        if not isinstance(other, type(self)): return NotImplemented
        return self.meta.ID == other.meta.ID

class TagParser():
    def __init__(self, args, criteria : Criteria, absolute_path=False, all_svm_tag_names=None):
        self.args = args
        self.data_file = args.data_file
        self.auto_file = args.auto_file
        self.exif_file = args.exif_file
        self.hash_file = args.hash_file
        self.hash_pickle = args.hash_pickle
        self.lines_file = args.lines_file

        self.criteria = criteria
        self.save_folder = criteria.get_save_folder()
        self.absolute_path = absolute_path
        self.all_svm_tag_names = all_svm_tag_names # ALl interested tags
        self.all_svm_tags = self._load_files()

    def _load_files(self):
        metadata_list = self.criteria.get_metadata_pickle()
        if metadata_list == None or len(metadata_list) == 0:
            # import pdb; pdb.set_trace()
            raise NotImplementedError()
        
        # metadata_list = metadata_list[:10000] #TODO: Remove this line
        for meta in tqdm(metadata_list):
            if not self.absolute_path:
                meta.get_metadata().IMG_PATH = os.path.abspath(os.path.join(self.save_folder, meta.get_metadata().IMG_PATH))
            width, height = imagesize.get(meta.get_metadata().IMG_PATH)
            meta.get_metadata().WIDTH, meta.get_metadata().HEIGHT = width, height
            meta.get_metadata().ASPECT_RATIO = max(width, height) / min(width, height)
        print("Computed the weight and height and aspect ratio for all images")

        all_svm_tags = {}
        for meta in tqdm(metadata_list):
            for t in meta.get_metadata().AUTO_TAG_SCORES:
                if self.all_svm_tag_names != None and t not in self.all_svm_tag_names:
                    continue
                # TODO: TAG score threshold
                if t not in all_svm_tags:
                    all_svm_tags[t] = {}
                    for score in SCORE_BUCKET:
                        all_svm_tags[t][score] = []
                
                bucket_idx = 0
                for i, score in enumerate(SCORE_BUCKET):
                    if meta.get_metadata().AUTO_TAG_SCORES[t] >= score:
                        bucket_idx = i
                
                all_svm_tags[t][SCORE_BUCKET[bucket_idx]].append(meta.get_metadata())

        return all_svm_tags
    
    def prepare_img_table(self, t, all_meta_with_tag_t, tag_analysis_page, summary_row, tag_score_func=lambda i, t: i.AUTO_TAG_SCORES[t], sortcol="confidence score", optional_title=None):
        imgs = [os.path.relpath(i.IMG_PATH, start=os.path.dirname(tag_analysis_page)) for i in all_meta_with_tag_t]
        conf_score = [tag_score_func(i, t) for i in all_meta_with_tag_t]
        date_taken = [parser.isoparse(i.DATE_TAKEN) for i in all_meta_with_tag_t]
        date_uploaded = [datetime.utcfromtimestamp(int(i.DATE_UPLOADED)) for i in all_meta_with_tag_t]
        list_invalid_dates = [taken >= uploaded for taken, uploaded in zip(date_taken, date_uploaded)]
        invalid_dates = sum(list_invalid_dates)
        # if invalid_dates > 0:
        #     print(f"{t} has {invalid_dates} invalid dates")
            # import pdb; pdb.set_trace()
        date_taken = [str(d) for d in date_taken]
        date_uploaded = [("INVALID: " if i else "")+str(d) for i, d in zip(list_invalid_dates, date_uploaded)]
        titles = [i.TITLE for i in all_meta_with_tag_t]
        user_tags = [i.USER_TAGS for i in all_meta_with_tag_t]
        machine_tags = [i.MACHINE_TAGS for i in all_meta_with_tag_t]
        description = [i.DESCRIPTION for i in all_meta_with_tag_t]
        sizes = [f"{i.WIDTH:d} , {i.HEIGHT:d}" for i in all_meta_with_tag_t]
        aspect_ratios = [f'{i.ASPECT_RATIO:.5f}' for i in all_meta_with_tag_t]
        ids = [i.ID for i in all_meta_with_tag_t]
        tag_and_scores = [tag_and_score(i) for i in all_meta_with_tag_t]
        cols = [imgs, ids, conf_score, date_taken, date_uploaded, sizes, aspect_ratios, titles, tag_and_scores, user_tags, machine_tags, description]
        
        headers = [f'Image with tag {t}', 'YFCC ID', 'confidence score', 'date taken', 'date uploaded', 'size (w x h)', 'aspect ratio', 'title', 'SVM tags', 'user tags', 'machine tags', 'description']
        make_table_html(headers,
                        cols,
                        summary_row=summary_row,
                        sortcol=sortcol,
                        image_col_name=f'Image with tag {t}',
                        href=tag_analysis_page,
                        html_title=f'Example with tag {t}' if optional_title == None else optional_title)

    def prepare_img_table_without_tag(self, all_meta_list, analysis_page, sort_func, sort_name, sort_converter_to_str, imgs_per_page=1000):
        # First remove all duplicates
        all_meta_list = [m.meta for m in list(set([_Metadata(m) for m in all_meta_list]))]
        
        n_meta = len(all_meta_list)
        
        all_meta_list_sorted = sorted(all_meta_list, key=lambda x: sort_func(x))
        
        n_invalid_dates = self.get_invalid_dates(all_meta_list_sorted)

        n_meta = len(all_meta_list)
        if n_meta == 0:
            import pdb; pdb.set_trace()
            return
        
        mean_score = sort_converter_to_str(sum([sort_func(m) for m in all_meta_list]) / len(all_meta_list))

        analysis_subpages = []
        analysis_subpages_descriptions = []

        analysis_name = analysis_page.split(os.sep)[-1][:-5]
        analysis_subfolder = os.path.join(self.index_folder, f"analysis_{analysis_name}")
        if not os.path.exists(analysis_subfolder):
            os.makedirs(analysis_subfolder)

        meta_chunks = chunks(all_meta_list_sorted, imgs_per_page)
        for chunk_idx, meta_chunk in enumerate(meta_chunks):
            
            lower_bound = chunk_idx*imgs_per_page
            upper_bound = min(lower_bound + imgs_per_page, len(all_meta_list_sorted))
            analysis_subpage = os.path.join(analysis_subfolder, f"analysis_{lower_bound}_{upper_bound}.html")

            mean_score_chunk = sort_converter_to_str(sum([sort_func(m) for m in meta_chunk]) / len(meta_chunk))
            min_score_chunk = sort_converter_to_str(min([sort_func(m) for m in meta_chunk]))
            max_score_chunk = sort_converter_to_str(max([sort_func(m) for m in meta_chunk]))
            analysis_subpages_description = f"{sort_name} (Image Index {lower_bound} to {upper_bound}) (Min is {min_score_chunk}, max is {max_score_chunk})"
            n_invalid_dates_chunk = self.get_invalid_dates(meta_chunk)

            mean_score_str = f"Mean: {mean_score} (of all {len(all_meta_list)} images). For {len(meta_chunk)} imgs in this page the mean is: {mean_score_chunk}."
            invalid_str = f"Invalid: {n_invalid_dates}. In this page {n_invalid_dates_chunk} are invalid."
            summary_row = [mean_score_str, '', "", invalid_str, "", "", "", "", "", "", ""]
            self._img_table_no_tag(meta_chunk, analysis_subpage, summary_row)
            analysis_subpages.append(os.path.relpath(analysis_subpage, start=self.index_folder))
            analysis_subpages_descriptions.append(analysis_subpages_description)
        
        make_index_html(analysis_subpages, analysis_subpages_descriptions, href=analysis_page)

    def _img_table_no_tag(self, all_meta_list, html_page, summary_row):
        imgs = [os.path.relpath(i.IMG_PATH, start=html_page) for i in all_meta_list]
        tag_and_scores = [tag_and_score(i) for i in all_meta_list]
        date_taken = [parser.isoparse(i.DATE_TAKEN) for i in all_meta_list]
        date_uploaded = [datetime.utcfromtimestamp(int(i.DATE_UPLOADED)) for i in all_meta_list]
        list_invalid_dates = [taken >= uploaded for taken, uploaded in zip(date_taken, date_uploaded)]
        invalid_dates = sum(list_invalid_dates)
        date_taken = [str(d) for d in date_taken]
        date_uploaded = [("INVALID: " if i else "")+str(d) for i, d in zip(list_invalid_dates, date_uploaded)]
        titles = [i.TITLE for i in all_meta_list]
        user_tags = [i.USER_TAGS for i in all_meta_list]
        machine_tags = [i.MACHINE_TAGS for i in all_meta_list]
        description = [i.DESCRIPTION for i in all_meta_list]
        sizes = [f"{i.WIDTH:d} , {i.HEIGHT:d}" for i in all_meta_list]
        aspect_ratios = [f'{i.ASPECT_RATIO:.5f}' for i in all_meta_list]
        ids = [i.ID for i in all_meta_list]
        cols = [imgs, ids, date_taken, date_uploaded, sizes, aspect_ratios, tag_and_scores, titles, user_tags, machine_tags, description]
        headers = [f'Image', 'YFCC ID', 'date taken', 'date uploaded', 'size (w,h)', 'aspect ratio', 'tag and scores', 'title', 'user tags', 'machine tags', 'description']
        
        make_table_html(headers,
                        cols,
                        summary_row=summary_row,
                        sortcol="date uploaded",
                        image_col_name=f'Image',
                        href=html_page,
                        html_title=f'Example')

    def is_invalid_date_meta(self, meta):
        try:
            date_taken = parser.isoparse(meta.DATE_TAKEN)
            date_uploaded = datetime.utcfromtimestamp(int(meta.DATE_UPLOADED))
            return date_taken >= date_uploaded
        except:
            return True
    
    def is_weird_aspect_ratio_meta(self, meta):
        return meta.ASPECT_RATIO > WEIRD_ASPECT_RATIO

    def get_invalid_dates(self, meta_list):
        list_invalid_dates = [self.is_invalid_date_meta(meta) for meta in meta_list]
        invalid_dates = sum(list_invalid_dates)
        return int(invalid_dates)
    
    def get_mean_scores(self, t, meta_list):
        conf_score = [i.AUTO_TAG_SCORES[t] for i in meta_list]
        mean_score = sum(conf_score)/len(conf_score)
        return mean_score
    
    def get_extreme_scores(self, t, meta_list):
        conf_score = [i.AUTO_TAG_SCORES[t] for i in meta_list]
        min_score = min(conf_score)
        max_score = max(conf_score)
        return min_score, max_score

    def generate_tag_dict_html(self, tag_dict, conf_threshold=SCORE_BUCKET[-1], imgs_per_page=500, excluded_ids=None):
        old_folder_names = os.path.abspath(self.save_folder).split(os.sep)
        folder_name = old_folder_names[-1]
        old_folder_names[-1] = "html/"+folder_name
        self.all_img_folder = os.sep.join(old_folder_names[:-1])
        self.html_folder = os.sep.join(old_folder_names)
        self.index_folder = os.path.join(self.html_folder, "index")
        self.analysis_folder = os.path.join(self.html_folder, "analysis")
        # self.index_page = os.path.join(self.all_img_folder, f"index_{folder_name}.html")
        self.index_page = os.path.join(self.all_img_folder, f"index_{folder_name}.html")
        tag_main_page = os.path.join(self.index_folder, "tags.html")
        tag_main_page_description = "All valid images in each SVM tag groups (date taken < date uploaded) "

        index_pages = [tag_main_page]
        index_pages_descriptions = [tag_main_page_description]

        if excluded_ids:
            excluded_page = os.path.join(self.index_folder, "excluded.html")
            excluded_page_description = "All manually filtered out images in each SVM tag group (date taken < date uploaded) "

            included_page = os.path.join(self.index_folder, "included.html")
            included_page_description = "All non-filtered out images in each SVM tag group (date taken < date uploaded) "

            time_page = os.path.join(self.index_folder, "time.html")
            time_page_description = "Time Analysis for all non-filtered out images"

            index_pages += [included_page, excluded_page, time_page]
            index_pages_descriptions += [included_page_description, excluded_page_description, time_page_description]

            included_pages = []
            included_descriptions = []

            excluded_pages = []
            excluded_descriptions = []

            time_pages = []
            time_descriptions = []

        index_pages = [os.path.relpath(p, start=self.all_img_folder) for p in index_pages]
        make_index_html(index_pages,
                        index_pages_descriptions,
                        href=self.index_page)
        
        if not os.path.exists(self.index_folder):
            os.makedirs(self.index_folder)
        
        tag_pages = []
        tag_descriptions = []

        all_svm_tags_keys = tag_dict.keys()
        all_meta_included = []
        for t in tqdm(all_svm_tags_keys):
            all_meta_with_tag_t = [x.metadata for x in tag_dict[t]]

            for meta in all_meta_with_tag_t:
                meta.IMG_PATH = os.path.abspath(os.path.join(self.save_folder, meta.IMG_PATH))
            
            n_meta = len(all_meta_with_tag_t)
            if n_meta == 0:
                print(f"Skipping {t} because no images")
                continue
            else:
                tag_descriptions.append(f"{t.replace(' ', '_')} ({n_meta:6d} images)")
                tag_analysis_page = os.path.join(self.index_folder, f"index_{t}.html")
                tag_pages.append(os.path.relpath(tag_analysis_page, start=self.index_folder))
                self.prepare_img_table_for_tag(
                    t,
                    tag_analysis_page,
                    all_meta_with_tag_t,
                    imgs_per_page,
                    sortcol="confidence score",
                    tag_score_func=lambda i, t: i.AUTO_TAG_SCORES[t],
                    tagname=t.replace(' ', '_'),
                    score_func=lambda x: x.AUTO_TAG_SCORES[t],
                    score_to_str=lambda s: f'{s:.3f}'
                )

            # if t == 'map':
            #     debug_tag(t, all_meta_with_tag_t, conf_score_max=0.973)
            if excluded_ids:
                all_meta_with_tag_t_included = []
                all_meta_with_tag_t_excluded = []
                for meta in all_meta_with_tag_t:
                    if int(meta.ID) in excluded_ids:
                        all_meta_with_tag_t_excluded.append(meta)
                    else:
                        all_meta_with_tag_t_included.append(meta)

                all_meta_included += all_meta_with_tag_t_included

                n_meta_included = len(all_meta_with_tag_t_included)
                n_meta_excluded = len(all_meta_with_tag_t_excluded)
                included_descriptions.append(f"{t.replace(' ', '_')} ({n_meta_included:6d} images)")
                # print(f"{t.replace(' ', '_')} ({n_meta_included:6d} images)")
                included_analysis_page = os.path.join(self.index_folder, f"index_{t}_included.html")
                included_pages.append(os.path.relpath(included_analysis_page, start=self.index_folder))

                time_analysis_page = os.path.join(self.analysis_folder, f"{t}")
                if not os.path.exists(time_analysis_page): os.makedirs(time_analysis_page)
                time_pages.append(os.path.relpath(time_analysis_page, start=self.index_folder))
                time_descriptions.append(f"{t.replace(' ', '_')} ({n_meta_included:6d} images)")

                plot_time_buckets(all_meta_with_tag_t_included, time_analysis_page, mode='year', date='date_uploaded', optional_name=f'{t}')

                excluded_descriptions.append(f"{t.replace(' ', '_')} ({n_meta_excluded:6d} images)")
                excluded_analysis_page = os.path.join(self.index_folder, f"index_{t}_excluded.html")
                excluded_pages.append(os.path.relpath(excluded_analysis_page, start=self.index_folder))
                self.prepare_img_table_for_tag(
                    t,
                    included_analysis_page,
                    all_meta_with_tag_t_included,
                    imgs_per_page,
                    sortcol="confidence score",
                    tag_score_func=lambda i, t: i.AUTO_TAG_SCORES[t],
                    tagname=t.replace(' ', '_'),
                    score_func=lambda x: x.AUTO_TAG_SCORES[t],
                    score_to_str=lambda s: f'{s:.3f}'
                )
                if len(all_meta_with_tag_t_excluded) > 0:
                    self.prepare_img_table_for_tag(
                        t,
                        excluded_analysis_page,
                        all_meta_with_tag_t_excluded,
                        imgs_per_page,
                        sortcol="confidence score",
                        tag_score_func=lambda i, t: i.AUTO_TAG_SCORES[t],
                        tagname=t.replace(' ', '_'),
                        score_func=lambda x: x.AUTO_TAG_SCORES[t],
                        score_to_str=lambda s: f'{s:.3f}'
                    )
                    



        #TODO: Comment back
        make_index_html(tag_pages, tag_descriptions, href=tag_main_page)
        if excluded_ids:
            make_index_html(included_pages, included_descriptions, href=included_page)
            make_index_html(excluded_pages, excluded_descriptions, href=excluded_page)
            make_index_html(time_pages, time_descriptions, href=time_page)

        # return #TODO: remove
        print(f"Saved to {self.index_page}")

    def generate_img_html(self, conf_threshold=SCORE_BUCKET[-1], imgs_per_page=500, print_threshold_page=True, print_outlier_pages=True):
        old_folder_names = os.path.abspath(self.save_folder).split(os.sep)
        folder_name = old_folder_names[-1]
        old_folder_names[-1] = "html/"+folder_name
        self.all_img_folder = os.sep.join(old_folder_names[:-1])
        self.html_folder = os.sep.join(old_folder_names)
        self.index_folder = os.path.join(self.html_folder, "index")
        # self.index_page = os.path.join(self.all_img_folder, f"index_{folder_name}.html")
        self.index_page = os.path.join(self.all_img_folder, f"index_{folder_name}.html")
        tag_main_page = os.path.join(self.index_folder, "tags.html")
        tag_main_page_description = "All valid images in each SVM tag groups (date taken < date uploaded) "

        invalid_main_page = os.path.join(self.index_folder, "invalids.html")
        invalid_main_page_description = "All invalid images"

        weird_aspect_ratio_page = os.path.join(self.index_folder, "weird_aspect_ratios.html")
        weird_aspect_ratio_page_description = f"All valid images with weird aspect ratio (> {WEIRD_ASPECT_RATIO:.2f})"
        
        dynamic_tags_page = os.path.join(self.index_folder, "dynamic_tags.html")
        dynamic_tags_page_description = f"All valid images in each SVM tag groups with confidence > {conf_threshold:.3f}"
        
        user_tags_page = os.path.join(self.index_folder, "user_tags.html")
        user_tags_page_description = f"All valid images in each user tag groups"
        
        if not os.path.exists(self.index_folder):
            os.makedirs(self.index_folder)
        
        tag_pages = []
        tag_descriptions = []

        dynamic_tag_pages = []
        dynamic_tag_descriptions = []

        user_tag_pages = []
        user_tag_descriptions = []
        all_valid_meta_list = [] # Only used for user tags
        darkroom_user_tags = read_darkroom()
        
        all_invalid_date_meta = []
        all_weird_aspect_ratio_meta = []

        all_svm_tags_keys = sorted(list(self.all_svm_tags.keys()), key=lambda x: sum([len(self.all_svm_tags[x][s]) for s in SCORE_BUCKET]))
        for t in tqdm(all_svm_tags_keys):
            all_meta_with_tag_t = []
            for threshold in self.all_svm_tags[t]:
                all_meta_with_tag_t += self.all_svm_tags[t][threshold]
            
            # Update the meta list so that all date are valid
            all_meta_with_tag_t_valid_date = []
            for meta in all_meta_with_tag_t:
                if self.is_invalid_date_meta(meta):
                    all_invalid_date_meta.append(meta)
                else:
                    all_meta_with_tag_t_valid_date.append(meta) 
            all_meta_with_tag_t = all_meta_with_tag_t_valid_date

            for meta in all_meta_with_tag_t:
                if self.is_weird_aspect_ratio_meta(meta):
                    all_weird_aspect_ratio_meta.append(meta)
                else:
                    all_valid_meta_list.append(meta)

            # continue # TODO:remove
            n_meta = len(all_meta_with_tag_t)
            if n_meta == 0:
                print(f"Skipping {t} because no valid date")
                continue
            else:
                tag_descriptions.append(f"{t.replace(' ', '_')} ({n_meta:6d} images)")
                tag_analysis_page = os.path.join(self.index_folder, f"index_{t}.html")
                tag_pages.append(os.path.relpath(tag_analysis_page, start=self.index_folder))
                self.prepare_img_table_for_tag(
                    t,
                    tag_analysis_page,
                    all_meta_with_tag_t,
                    imgs_per_page,
                    sortcol="confidence score",
                    tag_score_func=lambda i, t: i.AUTO_TAG_SCORES[t],
                    tagname=t.replace(' ', '_'),
                    score_func=lambda x: x.AUTO_TAG_SCORES[t],
                    score_to_str=lambda s: f'{s:.3f}'
                )
            
            if print_threshold_page:
                all_meta_with_tag_t_threshold = list(filter(lambda x : x.AUTO_TAG_SCORES[t] > conf_threshold, all_meta_with_tag_t))
                n_meta_threshold = len(all_meta_with_tag_t_threshold)
                if n_meta_threshold == 0:
                    print(f"Skipping {t} because no valid date")
                else:
                    dynamic_tag_descriptions.append(f"{t.replace(' ', '_')} ({n_meta_threshold:6d} images)")
                    dynamic_tag_analysis_page = os.path.join(self.index_folder, f"index_{t}_threshold_{conf_threshold:.3f}.html")
                    dynamic_tag_pages.append(os.path.relpath(dynamic_tag_analysis_page, start=self.index_folder))
                    self.prepare_img_table_for_tag(
                        t,
                        dynamic_tag_analysis_page,
                        all_meta_with_tag_t_threshold,
                        imgs_per_page,
                        sortcol='date uploaded',
                        tag_score_func=lambda i, t: i.AUTO_TAG_SCORES[t],
                        tagname=t.replace(' ', '_')+f" score > {conf_threshold:.3f}",
                        score_func=lambda x: int(x.DATE_UPLOADED),
                        score_to_str=lambda s: str(datetime.utcfromtimestamp(int(s))),
                    )
            # score_str = " ".join([f" >{i}({len(all_svm_tags[t][i]):6d})" for i in SCORE_BUCKET])

        # User tag analysis
        all_user_tags = {}
        for meta in all_valid_meta_list:
            user_tag_list = parse_user_tags(meta)
            for t in user_tag_list:
                if not t in all_user_tags:
                    all_user_tags[t] = []
                all_user_tags[t].append(meta)
        print(f"Number of total user tags for valid images is: {len(all_user_tags.keys())}")

        all_darkroom_user_tags = {}
        for d_tag in darkroom_user_tags:
            if d_tag in all_user_tags:
                all_darkroom_user_tags[d_tag] = [m.meta for m in list(set([_Metadata(m) for m in all_user_tags[d_tag]]))]
        
        print(f"Among all {len(darkroom_user_tags)} darkroom user tags there are {len(all_darkroom_user_tags.keys())} exists in all valid images.")
        
        new_darkroom_user_tags = []
        for d_tag in darkroom_user_tags:
            if d_tag in all_darkroom_user_tags:
                new_darkroom_user_tags.append(d_tag)
            
        for t in tqdm(new_darkroom_user_tags):
            all_meta_with_tag_t = all_darkroom_user_tags[t]
            n_meta = len(all_meta_with_tag_t)
            
            user_tag_descriptions.append(f"{t} ({n_meta:10d} images)")
            user_tag_analysis_page = os.path.join(self.index_folder, f"index_{t}_usertag.html")
            user_tag_pages.append(os.path.relpath(user_tag_analysis_page, start=self.index_folder))
            self.prepare_img_table_for_tag(
                t,
                user_tag_analysis_page,
                all_meta_with_tag_t,
                imgs_per_page,
                sortcol='date uploaded',
                tag_score_func=lambda i, t: 1,
                tagname=t,
                score_func=lambda x: int(x.DATE_UPLOADED),
                score_to_str=lambda s: str(datetime.utcfromtimestamp(int(s))),
            )



        #TODO: Comment back
        make_index_html(tag_pages, tag_descriptions, href=tag_main_page)
        if print_threshold_page:
            make_index_html(dynamic_tag_pages, dynamic_tag_descriptions, href=dynamic_tags_page)
        make_index_html(user_tag_pages, user_tag_descriptions, href=user_tags_page)

        if print_outlier_pages:
            self.prepare_img_table_without_tag(
                all_weird_aspect_ratio_meta,
                weird_aspect_ratio_page,
                sort_func=lambda x: x.ASPECT_RATIO,
                sort_name="aspect ratio",
                sort_converter_to_str=lambda x: f'{x:.4f}',
                imgs_per_page=imgs_per_page,
            )
        
            new_all_invalid_date_meta = []
            for meta in all_invalid_date_meta:
                if meta.DATE_TAKEN != 'null':
                    new_all_invalid_date_meta.append(meta)
            print(f"{len(new_all_invalid_date_meta)} out of {len(all_invalid_date_meta)} are not null (date taken).")
            all_invalid_date_meta = new_all_invalid_date_meta
            self.prepare_img_table_without_tag(
                all_invalid_date_meta,
                invalid_main_page,
                sort_func=lambda x: (parser.isoparse(x.DATE_TAKEN) - datetime.utcfromtimestamp(int(x.DATE_UPLOADED))).total_seconds(),
                sort_name="time between taken and uploaded",
                sort_converter_to_str=lambda x: f'{x:.4f} seconds',
                imgs_per_page=imgs_per_page,
            )

        # return #TODO: remove
        index_pages = [tag_main_page, invalid_main_page, weird_aspect_ratio_page, dynamic_tags_page, user_tags_page]
        index_pages = [os.path.relpath(p, start=self.all_img_folder) for p in index_pages]
        index_pages_descriptions = [tag_main_page_description, invalid_main_page_description, weird_aspect_ratio_page_description, dynamic_tags_page_description, user_tags_page_description]
        make_index_html(index_pages,
                        index_pages_descriptions,
                        href=self.index_page)
        print(f"Saved to {self.index_page}")
    
    def prepare_img_table_for_tag(self, t, tag_analysis_page, all_meta_with_tag_t, imgs_per_page, tagname, score_func, score_to_str, tag_score_func=lambda i, t: i.AUTO_TAG_SCORES[t], sortcol="confidence score"):
        all_meta_with_tag_t_sorted = sorted(all_meta_with_tag_t, key=score_func)
        n_invalid_dates = self.get_invalid_dates(all_meta_with_tag_t_sorted)
        mean_score = score_to_str(sum([score_func(meta) for meta in all_meta_with_tag_t_sorted]) / len(all_meta_with_tag_t_sorted))

        n_meta = len(all_meta_with_tag_t_sorted)
        if n_meta > imgs_per_page:
            tag_analysis_subpages = []
            tag_analysis_subpages_descriptions = []
            meta_chunks = chunks(all_meta_with_tag_t_sorted, imgs_per_page)
            for chunk_idx, meta_chunk in enumerate(meta_chunks):
                tag_analysis_subfolder = os.path.join(self.index_folder, f"index_{tagname}")
                if not os.path.exists(tag_analysis_subfolder):
                    os.makedirs(tag_analysis_subfolder)
                
                lower_bound = chunk_idx*imgs_per_page
                upper_bound = min(lower_bound + imgs_per_page, len(all_meta_with_tag_t_sorted))
                tag_analysis_subpage = os.path.join(tag_analysis_subfolder, f"index_{lower_bound}_{upper_bound}.html")
                mean_score_chunk = score_to_str(sum([score_func(meta) for meta in meta_chunk]) / len(meta_chunk))
                min_score_chunk = score_to_str(min([score_func(meta) for meta in meta_chunk]))
                max_score_chunk = score_to_str(max([score_func(meta) for meta in meta_chunk]))
                tag_analysis_subpages_description = f"{tagname} (Image Index {lower_bound} to {upper_bound}) (Min is {min_score_chunk}, max is {max_score_chunk})"
                n_invalid_dates_chunk = self.get_invalid_dates(meta_chunk)

                mean_score_str = f"Mean: {mean_score} (of all {len(all_meta_with_tag_t_sorted)} images). For {len(meta_chunk)} imgs in this page mean is: {mean_score_chunk}."
                invalid_str = f"Invalid: {n_invalid_dates}. In this page {n_invalid_dates_chunk} are invalid."
                summary_row = ["", '', mean_score_str, "", invalid_str, "", "", "", "", "", "", ""]
                self.prepare_img_table(
                    t,
                    meta_chunk,
                    tag_analysis_subpage,
                    summary_row,
                    sortcol=sortcol,
                    tag_score_func=tag_score_func,
                    optional_title=f'Example with tag {tagname} for {lower_bound} to {upper_bound} images'
                )
                tag_analysis_subpages.append(os.path.relpath(tag_analysis_subpage, start=self.index_folder))
                tag_analysis_subpages_descriptions.append(tag_analysis_subpages_description)
            make_index_html(tag_analysis_subpages, tag_analysis_subpages_descriptions, href=tag_analysis_page)
        else:
            mean_score_str = f"Mean Score is {mean_score} ({len(all_meta_with_tag_t_sorted)} images)"
            invalid_str = f"Invalid: {n_invalid_dates}"
            summary_row = ["", '', mean_score_str, "", invalid_str, "", "", "", "", "", "", ""]
            self.prepare_img_table(
                t,
                all_meta_with_tag_t_sorted,
                tag_analysis_page,
                summary_row,
                sortcol=sortcol,
                tag_score_func=tag_score_func,
                optional_title=None
            )

def remove_duplicate(all_meta_list):
    all_meta_list = [m.meta for m in list(set([_Metadata(m) for m in all_meta_list]))]
    return all_meta_list

def parse_user_tags(meta):
    tag_list = meta.USER_TAGS.split(",")
    return tag_list

def read_darkroom(filename='./flickr_darkroom_usertags.txt'):
    with open(filename) as f:
        darkroom_user_tags = f.read().splitlines()
    return darkroom_user_tags

def chunks(lst, n):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

def tag_and_score(meta):
    sorted_k = sorted(meta.AUTO_TAG_SCORES.keys(), key=lambda x: meta.AUTO_TAG_SCORES[x])
    strs = [f"{t.replace(' ','_')}:{meta.AUTO_TAG_SCORES[t]:.2f}" for t in sorted_k]
    return "|".join(strs)

def print_tag_analysis(all_svm_tags, score_threshold=SCORE_BUCKET[-1]):
    all_svm_tags_keys = sorted(list(all_svm_tags.keys()), key=lambda x: len(all_svm_tags[x][score_threshold]))
    for t in all_svm_tags_keys:
        score_str = " ".join([f" >{i}({len(all_svm_tags[t][i]):6d})" for i in SCORE_BUCKET])

        print(f"{t:30s}:{score_str}")
    print(f"Tags: {len(all_svm_tags.keys())}")

def debug_tag(t, meta_list, conf_score_max=1.):
    meta_list = sorted(meta_list, key=lambda x: x.AUTO_TAG_SCORES[t])
    meta_list = list(filter(lambda x: x.AUTO_TAG_SCORES[t] < conf_score_max, meta_list))
    with open(f'temp_{t}.txt', "w+") as f:
        for meta in meta_list:
            f.write(meta.ID + "\n")
    print(f"Saved at temp_{t}.txt")

if __name__ == "__main__":
    args = argparser.parse_args()
    if args.fetch_by_tag:
        raise NotImplementedError()
        # criteria = ImageByAutoTag(args)
    elif args.random_images:
        raise NotImplementedError()
        # criteria = ImageByRandom(args)
    criteria = AllImages(args)
    
        
    tag_parser = TagParser(args, criteria)

    print_tag_analysis(tag_parser.all_svm_tags)
    tag_parser.generate_img_html()
        
    